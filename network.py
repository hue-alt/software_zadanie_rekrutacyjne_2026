from collections import deque
import threading
import time

from communication_library import ids
from communication_library.communication_manager import CommunicationManager, TransportType
from communication_library.exceptions import (
    ClosedTransportError,
    CommunicationError,
    TransportError,
    TransportTimeoutError,
    UnregisteredCallbackError,
)
from communication_library.frame import Frame
from communication_library.tcp_transport import TcpSettings
from state import TelemetryState

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 3000


class RocketClient:
    def __init__(
        self,
        state: TelemetryState,
        proxyHost: str = DEFAULT_PROXY_HOST,
        proxyPort: int = DEFAULT_PROXY_PORT,
    ) -> None:
        self.state = state
        self.proxyHost = proxyHost
        self.proxyPort = proxyPort

        self.manager = CommunicationManager()
        self.manager.change_transport_type(TransportType.TCP)

        self.isConnected = False
        self.shouldRun = False
        self.sendQueue = deque()

        self._registerCallbacks()

    def _registerCallbacks(self) -> None:
        self.manager.clear_callbacks()
        for deviceId in self.state.sensorNames:
            frame = Frame(
                ids.BoardID.SOFTWARE, ids.PriorityID.LOW, ids.ActionID.FEED,
                ids.BoardID.ROCKET, ids.DeviceID.SENSOR, deviceId,
                ids.DataTypeID.FLOAT, ids.OperationID.SENSOR.value.READ,
            )
            self.manager.register_callback(self._onFrame, frame)

        for deviceId in self.state.servoNames:
            frame = Frame(
                ids.BoardID.SOFTWARE, ids.PriorityID.LOW, ids.ActionID.FEED,
                ids.BoardID.ROCKET, ids.DeviceID.SERVO, deviceId,
                ids.DataTypeID.INT16, ids.OperationID.SERVO.value.POSITION,
            )
            self.manager.register_callback(self._onFrame, frame)

    def start(self) -> None:
        if not self.shouldRun:
            self.shouldRun = True
            threading.Thread(target=self._commLoop, daemon=True).start()

    def stop(self) -> None:
        self.shouldRun = False
        try:
            if self.manager.is_connected:
                self.manager.disconnect()
        except Exception:
            pass
        self.isConnected = False

    def setServo(self, servoName: str, position: int) -> None:
        frame = Frame(
            ids.BoardID.ROCKET, ids.PriorityID.HIGH, ids.ActionID.SERVICE,
            ids.BoardID.SOFTWARE, ids.DeviceID.SERVO, self.state.servoIds[servoName],
            ids.DataTypeID.INT16, ids.OperationID.SERVO.value.POSITION, (int(position),),
        )
        self.sendQueue.append(frame)
        self.state.addLog(f"TX SERVICE -> servo {servoName} = {position}")

    def setRelay(self, relayName: str, shouldOpen: bool) -> None:
        operationId = ids.OperationID.RELAY.value.OPEN if shouldOpen else ids.OperationID.RELAY.value.CLOSE
        frame = Frame(
            ids.BoardID.ROCKET, ids.PriorityID.HIGH, ids.ActionID.SERVICE,
            ids.BoardID.SOFTWARE, ids.DeviceID.RELAY, self.state.relayIds[relayName],
            ids.DataTypeID.NO_DATA, operationId, (),
        )
        self.sendQueue.append(frame)
        self.state.addLog(f"TX SERVICE -> relay {relayName} = {'OPEN' if shouldOpen else 'CLOSE'}")

    def _commLoop(self) -> None:
        lastConnectAttempt = 0.0
        while self.shouldRun:
            now = time.perf_counter()
            if not self.isConnected:
                if now - lastConnectAttempt > 1.5:
                    lastConnectAttempt = now
                    try:
                        self.manager.connect(TcpSettings(self.proxyHost, self.proxyPort))
                        self.isConnected = True
                        self.state.addLog(f"Połączono z proxy {self.proxyHost}:{self.proxyPort}")
                    except Exception:
                        self.isConnected = False
                time.sleep(0.1)
                continue

            try:
                while self.sendQueue:
                    self.manager.push(self.sendQueue.popleft())
                    self.manager.send()

                for packetIndex in range(25):
                    try:
                        self.manager.receive()
                    except UnregisteredCallbackError as err:
                        self._onFrame(err.frame)
                    except TransportTimeoutError:
                        break
            except (ClosedTransportError, TransportError, CommunicationError, OSError):
                self.isConnected = False
                self.state.addLog("Utracono połączenie z proxy")
                try:
                    self.manager.disconnect()
                except Exception:
                    pass

            time.sleep(0.02)

    def _onFrame(self, frame: Frame) -> None:
        now = time.perf_counter()
        if self.state.startTime is None:
            self.state.startTime = now

        actionId = int(frame.action)
        deviceType = int(frame.device_type)
        deviceId = int(frame.device_id)
        operationId = int(frame.operation)

        if actionId == int(ids.ActionID.FEED):
            self.state.feedCount += 1
            if deviceType == int(ids.DeviceID.SENSOR):
                self.state.updateSensor(deviceId, float(frame.data), now)
            elif deviceType == int(ids.DeviceID.SERVO):
                deviceName = self.state.servoNames.get(deviceId)
                if deviceName:
                    self.state.servos[deviceName] = int(frame.data)
                    if deviceName == "oxidizer_main":
                        self.state.updatePhaseAndHistory(now)

        elif actionId in (int(ids.ActionID.ACK), int(ids.ActionID.NACK)):
            if actionId == int(ids.ActionID.ACK):
                self.state.ackCount += 1
                if deviceType == int(ids.DeviceID.SERVO):
                    deviceName = self.state.servoNames.get(deviceId, f"servo_{deviceId}")
                    self.state.servos[deviceName] = int(frame.data)
                elif deviceType == int(ids.DeviceID.RELAY):
                    deviceName = self.state.relayNames.get(deviceId, f"relay_{deviceId}")
                    self.state.relays[deviceName] = 1 if operationId == int(ids.OperationID.RELAY.value.OPEN)
                else 0
                self.state.addLog(f"RX ACK <- {deviceName}")
            else:
                self.state.nackCount += 1
                self.state.addLog(f"RX NACK <- device_id={deviceId}")

