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
        self.phase = "Standby"
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
            if self.phase == "Landed" or (altitudeValue <= 0.2 and self.maxAltitude > 5.0):
                self.phase = "Landed"
            elif fuelLevel > 0.0 and self.servos["fuel_main"] == SERVO_OPEN:
                self.phase = "Powered Ascent"
            elif self.relays["parachute"] == 1 or self.phase == "Parachute Descent":
                if altitudeValue <= 0.2:
                    self.phase = "Landed"
                else:
                    self.phase = "Parachute Descent"
            elif self.velocity > 0.5:
                self.phase = "Coasting to Apogee"
            elif -2.0 <= self.velocity <= 0.5:
                self.phase = "Apogee Reached"
            else:
                self.phase = "Freefall Descent"
        else:
            intakesClosed = (
                self.servos["fuel_intake"] == SERVO_CLOSED
                and self.servos["oxidizer_intake"] == SERVO_CLOSED
            )
            if oxidizerLevel < 99.0:
                self.phase = "Filling Oxidizer Tank" if self.servos["oxidizer_intake"] == SERVO_OPEN else "Standby"
            elif fuelLevel < 99.0:
                self.phase = "Filling Fuel Tank" if self.servos["fuel_intake"] == SERVO_OPEN else "Oxidizer Loaded"
            elif 55.0 <= pressureValue <= 65.0 and intakesClosed:
                self.phase = "Ready for Launch"
            elif self.relays["oxidizer_heater"] == 1:
                self.phase = "Heating Oxidizer Tank"
            else:
                self.phase = "Fuel Loaded"

    def checkTouchdownTimeout(self, currentTime: float) -> None:
        if self.phase == "Landed" or self.maxAltitude <= 5.0:
            return
        if self.lastAltitudeTime is None:
            return
        if self.sensors["altitude"] <= 5.5 and self.velocity < 0.0:
            if currentTime - self.lastAltitudeTime > 1.2:
                self.sensors["altitude"] = 0.0
                self.velocity = 0.0
                self.phase = "Landed"
