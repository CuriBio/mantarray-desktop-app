# -*- coding: utf-8 -*-
"""Generic exceptions for the Mantarray GUI."""
from typing import Union


class MultiprocessingNotSetToSpawnError(Exception):
    def __init__(self, start_method: Union[str, None]):
        super().__init__(
            f"The multiprocessing start type has not been set to spawn, which is the only option on Windows. It is current set as '{start_method}'"
        )


class InvalidCommandFromMainError(Exception):
    pass


class UnrecognizedDebugConsoleCommandError(Exception):
    pass


class UnableToUploadLogFilesToS3(Exception):
    pass


class UnrecognizedCommandFromServerToMainError(Exception):
    pass


class UnrecognizedCommandFromMainToOkCommError(Exception):
    pass


class InvalidCustomerAccountIDPasswordError(Exception):
    pass


class UnrecognizedCommandFromMainToFileWriterError(Exception):
    pass


class UnrecognizedCommandFromMainToMcCommError(Exception):
    pass


class UnrecognizedCommandFromMainToDataAnalyzerError(Exception):
    pass


class UnrecognizedDataFrameFormatNameError(Exception):
    pass


class LocalServerPortAlreadyInUseError(Exception):
    pass


class AttemptToInitializeFIFOReadsError(Exception):
    pass


class AttemptToAddCyclesWhileSPIRunningError(Exception):
    pass


class FirstManagedReadLessThanOneRoundRobinError(Exception):
    pass


class InvalidDataFramePeriodError(Exception):
    pass


class MismatchedScriptTypeError(Exception):
    pass


class InvalidScriptCommandError(Exception):
    pass


class ScriptDoesNotContainEndCommandError(Exception):
    pass


class SystemStartUpError(Exception):
    pass


class InvalidBeta2FlagOptionError(Exception):
    pass


class UnrecognizedMantarrayNamingCommandError(Exception):
    pass


class UnrecognizedRecordingCommandError(Exception):
    pass


class UnrecognizedSimulatorTestCommandError(Exception):
    pass


class RecordingFolderDoesNotExistError(Exception):
    pass


class InvalidStopRecordingTimepointError(Exception):
    pass


class CalibrationFilesMissingError(Exception):
    pass


class FirmwareFileNameDoesNotMatchWireOutVersionError(Exception):
    pass


class BarcodeNotClearedError(Exception):
    pass


class BarcodeScannerNotRespondingError(Exception):
    pass


class ServerManagerNotInitializedError(Exception):
    pass


class ServerManagerSingletonAlreadySetError(Exception):
    """Helps ensure that test cases clean up after themselves."""


class InstrumentCommIncorrectHeaderError(Exception):
    pass


class UnrecognizedSerialCommModuleIdError(Exception):
    pass


class UnrecognizedSerialCommPacketTypeError(Exception):
    pass


class SerialCommPacketRegistrationTimeoutError(Exception):
    pass


class SerialCommPacketRegistrationReadEmptyError(Exception):
    pass


class SerialCommPacketRegistrationSearchExhaustedError(Exception):
    pass


class SerialCommNotEnoughAdditionalBytesReadError(Exception):
    pass


class SerialCommIncorrectChecksumFromInstrumentError(Exception):
    pass


class SerialCommIncorrectChecksumFromPCError(Exception):
    pass


class SerialCommIncorrectMagicWordFromMantarrayError(Exception):
    pass


class SerialCommPacketFromMantarrayTooSmallError(Exception):
    pass


class SerialCommMetadataValueTooLargeError(Exception):
    pass


class SerialCommTooManyMissedHandshakesError(Exception):
    pass


class SerialCommUntrackedCommandResponseError(Exception):
    pass


class SerialCommStatusBeaconTimeoutError(Exception):
    pass


class SerialCommCommandResponseTimeoutError(Exception):
    pass


class SerialCommHandshakeTimeoutError(Exception):
    pass


class SerialCommInvalidSamplingPeriodError(Exception):
    pass


class MagnetometerConfigUpdateWhileDataStreamingError(Exception):
    pass


class InstrumentRebootTimeoutError(Exception):
    pass


class IncorrectMagnetometerConfigFromInstrumentError(Exception):
    pass


class IncorrectSamplingPeriodFromInstrumentError(Exception):
    pass


class InstrumentDataStreamingAlreadyStartedError(Exception):
    pass


class InstrumentDataStreamingAlreadyStoppedError(Exception):
    pass


class StimulationProtocolUpdateWhileStimulatingError(Exception):
    pass


class StimulationProtocolUpdateFailedError(Exception):
    pass


class StimulationStatusUpdateFailedError(Exception):
    pass


class FirmwareUpdateCommandFailedError(Exception):
    pass


class FirmwareUpdateTimeoutError(Exception):
    pass


class MantarrayInstrumentError(Exception):
    """Errors occurring on the Mantarray instrument itself."""


class InstrumentFatalError(MantarrayInstrumentError):
    pass


class InstrumentSoftError(MantarrayInstrumentError):
    pass
