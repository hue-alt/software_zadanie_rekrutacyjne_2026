import threading
import time

from network import RocketClient
from state import SERVO_CLOSED, SERVO_OPEN, TelemetryState


class FlightController:
    def __init__(self, client: RocketClient, state: TelemetryState) -> None:
        self.client = client
        self.state = state
        self.autopilotActive = False

    def canIgniteSafely(self) -> tuple[bool, str]:
        if self.state.servos["fuel_intake"] == SERVO_OPEN or self.state.servos["oxidizer_intake"] == SERVO_OPEN:
            return False, "Intake valves are still open"

        if self.state.sensors["oxidizer_level"] < 99.0:
            return False, "Oxidizer tank is not full"

        if self.state.sensors["fuel_level"] < 99.0:
            return False, "Fuel tank is not full"

        pressure = self.state.sensors["oxidizer_pressure"]
        if pressure < 55.0:
            return False, f"Oxidizer pressure too low ({pressure:.1f} bar, required 55-65 bar)"

        if pressure > 65.0:
            return False, f"Critical oxidizer overpressure ({pressure:.1f} bar > 65 bar)"

        if self.state.phase in ["Powered Ascent", "Coasting to Apogee", "Apogee Reached", "Parachute Descent", "Freefall Descent", "Landed"]:
            return False, "Rocket has already launched"

        return True, "All systems nominal - ready for launch"

    def igniteEngine(self) -> None:
        isSafe, reason = self.canIgniteSafely()
        if not isSafe:
            self.state.addLog(f"Ignition blocked: {reason}")
            return

        def runSequence() -> None:
            self.client.setRelay("oxidizer_heater", False)
            self.client.setServo("fuel_main", SERVO_OPEN)
            self.client.setServo("oxidizer_main", SERVO_OPEN)
            time.sleep(0.25)
            self.client.setRelay("igniter", True)
            time.sleep(1.5)
            self.client.setRelay("igniter", False)

        threading.Thread(target=runSequence, daemon=True).start()

    def startAutopilot(self) -> None:
        if not self.autopilotActive:
            self.autopilotActive = True
            self.state.addLog("Autopilot started!")
            threading.Thread(target=self._autopilotLoop, daemon=True).start()

    def stopAutopilot(self) -> None:
        self.autopilotActive = False
        self.state.addLog("Autopilot stopped!")

    def resetSystem(self) -> None:
        self.autopilotActive = False
        self.state.reset()
        self.state.addLog("System state reset")

    def _autopilotLoop(self) -> None:
        flightStage = 1
        while self.autopilotActive and self.client.shouldRun:
            self.state.checkTouchdownTimeout(time.perf_counter())
            oxidizerLevel = self.state.sensors["oxidizer_level"]
            fuelLevel = self.state.sensors["fuel_level"]
            oxidizerPressure = self.state.sensors["oxidizer_pressure"]
            altitudeValue = self.state.sensors["altitude"]

            if flightStage == 1:
                if oxidizerLevel < 100.0:
                    if self.state.servos["oxidizer_intake"] != SERVO_OPEN:
                        self.client.setServo("oxidizer_intake", SERVO_OPEN)
                else:
                    self.client.setServo("oxidizer_intake", SERVO_CLOSED)
                    flightStage = 2

            elif flightStage == 2:
                if fuelLevel < 100.0:
                    if self.state.servos["fuel_intake"] != SERVO_OPEN:
                        self.client.setServo("fuel_intake", SERVO_OPEN)
                else:
                    self.client.setServo("fuel_intake", SERVO_CLOSED)
                    flightStage = 3

            elif flightStage == 3:
                if oxidizerPressure < 59.0:
                    if self.state.relays["oxidizer_heater"] == 0:
                        self.client.setRelay("oxidizer_heater", True)
                else:
                    self.client.setRelay("oxidizer_heater", False)
                    flightStage = 4

            elif flightStage == 4:
                self.igniteEngine()
                flightStage = 5

            elif flightStage == 5:
                isFuelEmpty = (fuelLevel <= 0.0)
                isHighEnough = (altitudeValue > 20.0)
                hasPassedApogee = (altitudeValue < self.state.maxAltitude and -25.0 < self.state.velocity <= 0.0)
                if isFuelEmpty and isHighEnough and hasPassedApogee:
                    self.client.setRelay("parachute", True)
                    flightStage = 6

            elif flightStage == 6:
                if self.state.phase == "Landed":
                    self.autopilotActive = False
                    self.state.addLog("Autopilot finished the flight successfully!")
                    break

            time.sleep(0.4)

