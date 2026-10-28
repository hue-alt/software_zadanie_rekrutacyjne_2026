from nicegui import app, ui
import sys
import time

from autopilot import FlightController
from network import RocketClient
from state import SERVO_CLOSED, SERVO_OPEN, TelemetryState

state = TelemetryState()
client = RocketClient(state)
controller = FlightController(client, state)

SERVO_LABELS = {
    "fuel_intake": "Fuel Intake Valve",
    "oxidizer_intake": "Oxidizer Intake Valve",
    "fuel_main": "Main Fuel Valve",
    "oxidizer_main": "Main Oxidizer Valve",
}

RELAY_LABELS = {
    "oxidizer_heater": "Oxidizer Tank Heater",
    "igniter": "Engine Igniter",
    "parachute": "Recovery Parachute",
}

app.on_startup(client.start)
app.on_shutdown(client.stop)


@ui.page("/")
def indexPage() -> None:
    ui.page_title("Rocket Dashboard")

    with ui.row().classes("w-full items-center justify-between p-2"):
        ui.label("ROCKET DASHBOARD").classes("text-xl font-bold")
        statusLabel = ui.label("Status: DISCONNECTED").classes("font-mono")

    with ui.row().classes("w-full gap-2 px-2 items-center"):
        ui.button("START AUTOPILOT", on_click=controller.startAutopilot)
        ui.button("STOP AUTOPILOT", on_click=controller.stopAutopilot)
        igniteButton = ui.button("IGNITION SEQUENCE", on_click=controller.igniteEngine)
        ui.button("RESET", on_click=controller.resetSystem)
        safetyLabel = ui.label("").classes("text-sm font-semibold")

    with ui.row().classes("w-full gap-4 p-2 items-start"):
        with ui.card().classes("w-72"):
            ui.label("SENSORS").classes("font-bold")
            phaseLabel = ui.label("Phase: Standby")
            altLabel = ui.label("Altitude: 0.0 m (Max: 0.0 m)")
            velLabel = ui.label("Velocity: 0.0 m/s")
            angleLabel = ui.label("Angle: 2.0 deg")
            pressLabel = ui.label("Oxidizer Pressure: 0.0 bar")
            oxLabel = ui.label("Oxidizer Level: 0.0 %")
            oxBar = ui.linear_progress(value=0.0, show_value=False)
            fuelLabel = ui.label("Fuel Level: 0.0 %")
            fuelBar = ui.linear_progress(value=0.0, show_value=False)

        with ui.card().classes("w-96"):
            ui.label("VALVES").classes("font-bold")
            servoLabels = {}
            for servoName in state.servoIds:
                displayName = SERVO_LABELS.get(servoName, servoName)
                with ui.row().classes("w-full items-center justify-between"):
                    servoLabels[servoName] = ui.label(f"{displayName}: CLOSED")
                    with ui.row().classes("gap-1"):
                        ui.button("OPEN", on_click=lambda targetServo=servoName: client.setServo(targetServo, SERVO_OPEN)).props("dense")
                        ui.button("CLOSE", on_click=lambda targetServo=servoName: client.setServo(targetServo, SERVO_CLOSED)).props("dense")

        with ui.card().classes("w-96"):
            ui.label("ONBOARD SYSTEMS").classes("font-bold")
            relayLabels = {}
            for relayName in state.relayIds:
                displayName = RELAY_LABELS.get(relayName, relayName)
                with ui.row().classes("w-full items-center justify-between"):
                    relayLabels[relayName] = ui.label(f"{displayName}: CLOSED")
                    with ui.row().classes("gap-1"):
                        ui.button("OPEN", on_click=lambda targetRelay=relayName: client.setRelay(targetRelay, True)).props("dense")
                        ui.button("CLOSE", on_click=lambda targetRelay=relayName: client.setRelay(targetRelay, False)).props("dense")

    with ui.card().classes("w-full mx-2"):
        ui.label("EVENT LOGS").classes("font-bold")
        logsLabel = ui.label("").classes("font-mono whitespace-pre-line text-xs")

    def refreshUi() -> None:
        state.checkTouchdownTimeout(time.perf_counter())
        if client.isConnected:
            connText = "CONNECTED"
        else:
            connText = "DISCONNECTED"

        statusLabel.text = (
            f"Connection: {connText} | Telemetry updates: {state.feedCount} | "
            f"Commands OK: {state.ackCount} | Errors: {state.nackCount}"
        )
        phaseLabel.text = f"Phase: {state.phase}"
        altLabel.text = f"Altitude: {state.sensors['altitude']:.1f} m (Max: {state.maxAltitude:.1f} m)"
        velLabel.text = f"Velocity: {state.velocity:+.1f} m/s"
        angleLabel.text = f"Angle: {state.sensors['angle']:.1f} deg"
        pressLabel.text = f"Oxidizer Pressure: {state.sensors['oxidizer_pressure']:.1f} bar"

        isSafe, reason = controller.canIgniteSafely()
        if isSafe:
            igniteButton.enable()
            safetyLabel.text = f"Safety Check: {reason}"
            safetyLabel.classes("text-green-600", remove="text-black")
        else:
            igniteButton.disable()
            safetyLabel.text = f"Ignition Locked: {reason}"
            safetyLabel.classes("text-black", remove="text-green-600")

        oxidizerValue = state.sensors["oxidizer_level"]
        fuelValue = state.sensors["fuel_level"]
        oxLabel.text = f"Oxidizer Level: {oxidizerValue:.1f} %"
        oxBar.value = round(oxidizerValue / 100.0, 3)
        fuelLabel.text = f"Fuel Level: {fuelValue:.1f} %"
        fuelBar.value = round(fuelValue / 100.0, 3)

        for servoName, labelWidget in servoLabels.items():
            displayName = SERVO_LABELS.get(servoName, servoName)
            currentPosition = state.servos[servoName]
            if currentPosition == 0:
                servoStatusText = "OPEN"
            else:
                servoStatusText = "CLOSED"
            labelWidget.text = f"{displayName}: {servoStatusText}"

        for relayName, labelWidget in relayLabels.items():
            displayName = RELAY_LABELS.get(relayName, relayName)
            currentRelayState = state.relays[relayName]
            if currentRelayState == 1:
                relayStatusText = "OPEN"
            else:
                relayStatusText = "CLOSED"
            labelWidget.text = f"{displayName}: {relayStatusText}"

        formattedLogs = []
        for rawLog in list(state.logs)[:10]:
            cleanLog = rawLog.replace("TX SERVICE -> ", "Command: ")
            cleanLog = cleanLog.replace("RX ACK <- ", "Confirmed: ")
            cleanLog = cleanLog.replace("= 0", "-> OPEN").replace("= 100", "-> CLOSED")
            for rawKey, displayLabel in {**SERVO_LABELS, **RELAY_LABELS}.items():
                cleanLog = cleanLog.replace(f"servo {rawKey}", displayLabel)
                cleanLog = cleanLog.replace(f"relay {rawKey}", displayLabel)
                cleanLog = cleanLog.replace(rawKey, displayLabel)
            formattedLogs.append(cleanLog)
        logsLabel.text = "\n".join(formattedLogs)

    ui.timer(0.2, refreshUi)


if __name__ == "__main__":
    portNumber = 8080
    if len(sys.argv) > 1:
        portNumber = int(sys.argv[1])
    ui.run(host="127.0.0.1", port=portNumber, title="Rocket Dashboard", reload=False, show=False)

