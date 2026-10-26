from collections import deque
from datetime import datetime
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "simulator_config.yaml"
SERVO_OPEN = 0
SERVO_CLOSED = 100


class TelemetryState:
    def __init__(self, configPath: Path = CONFIG_PATH) -> None:
        with open(configPath, "r", encoding="utf-8") as configFile:
            rawDevices = yaml.safe_load(configFile)["devices"]

        self.servoIds = {name: int(deviceConfig["device_id"]) for name, deviceConfig in rawDevices["servo"].items()}
        self.relayIds = {name: int(deviceConfig["device_id"]) for name, deviceConfig in rawDevices["relay"].items()}
        self.sensorIds = {name: int(deviceConfig["device_id"]) for name, deviceConfig in rawDevices["sensor"].items()}

        self.servoNames = {deviceId: name for name, deviceId in self.servoIds.items()}
        self.relayNames = {deviceId: name for name, deviceId in self.relayIds.items()}
        self.sensorNames = {deviceId: name for name, deviceId in self.sensorIds.items()}

        self.logs = deque(maxlen=50)
        self.reset()

    def reset(self) -> None:
        self.sensors = {
            "fuel_level": 0.0,
            "oxidizer_level": 0.0,
            "altitude": 0.0,
            "oxidizer_pressure": 0.0,
            "angle": 2.0,
        }
        self.servos = {name: SERVO_CLOSED for name in self.servoIds}
        self.relays = {name: 0 for name in self.relayIds}

        self.velocity = 0.0
        self.maxAltitude = 0.0
        self.phase = "IDLE"
        self.feedCount = 0
        self.ackCount = 0
        self.nackCount = 0

        self.startTime = None
        self.lastAltitude = None
        self.lastAltitudeTime = None
        self.history = {
            "time": [],
            "altitude": [],
            "velocity": [],
            "pressure": [],
            "fuel": [],
            "oxidizer": [],
        }

    def addLog(self, messageText: str) -> None:
        formattedTime = datetime.now().strftime("%H:%M:%S")
        self.logs.appendleft(f"[{formattedTime}] {messageText}")

    def updateSensor(self, sensorId: int, sensorValue: float, currentTime: float) -> None:
        sensorName = self.sensorNames.get(sensorId)
        if not sensorName:
            return
        if sensorName == "altitude":
            if self.lastAltitude is not None and self.lastAltitudeTime is not None:
                deltaTime = currentTime - self.lastAltitudeTime
                if 0.02 <= deltaTime <= 10.0:
                    self.velocity = 0.0 if (sensorValue == 0.0 and self.lastAltitude == 0.0) else (sensorValue - self.lastAltitude) / deltaTime
            self.lastAltitude = sensorValue
            self.lastAltitudeTime = currentTime
            self.maxAltitude = max(self.maxAltitude, sensorValue)
        self.sensors[sensorName] = sensorValue

    def updatePhaseAndHistory(self, currentTime: float) -> None:
        oxidizerLevel = self.sensors["oxidizer_level"]
        fuelLevel = self.sensors["fuel_level"]
        altitudeValue = self.sensors["altitude"]
        pressureValue = self.sensors["oxidizer_pressure"]

        if self.maxAltitude > 2.0:
            if altitudeValue <= 0.05 and abs(self.velocity) <= 0.2:
                self.phase = "LANDED"
            elif fuelLevel > 0.0 and self.servos["fuel_main"] == SERVO_OPEN:
                self.phase = "FLIGHT"
            elif self.relays["parachute"] == 1:
                self.phase = "PARACHUTE_DEPLOYED"
            elif self.velocity <= 0.5:
                self.phase = "APOGEE"
            else:
                self.phase = "COASTING"
        else:
            if oxidizerLevel < 100.0:
                self.phase = "FILLING_OXIDIZER" if self.servos["oxidizer_intake"] == SERVO_OPEN else "IDLE"
            elif fuelLevel < 100.0:
                self.phase = "FILLING_FUEL" if self.servos["fuel_intake"] == SERVO_OPEN else "OXIDIZER_FILLED"
            elif 55.0 <= pressureValue <= 65.0:
                self.phase = "READY_TO_LAUNCH"
            elif self.relays["oxidizer_heater"] == 1:
                self.phase = "HEATING"
            else:
                self.phase = "FUEL_FILLED"

        elapsedSeconds = round(currentTime - (self.startTime or currentTime), 1)
        metricPairs = (
            ("time", f"{elapsedSeconds}s"),
            ("altitude", round(altitudeValue, 1)),
            ("velocity", round(self.velocity, 1)),
            ("pressure", round(pressureValue, 1)),
            ("fuel", round(fuelLevel, 1)),
            ("oxidizer", round(oxidizerLevel, 1)),
        )
        for metricKey, metricValue in metricPairs:
            self.history[metricKey].append(metricValue)
            if len(self.history[metricKey]) > 100:
                self.history[metricKey].pop(0)
