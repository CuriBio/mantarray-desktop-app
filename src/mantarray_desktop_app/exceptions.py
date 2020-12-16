# -*- coding: utf-8 -*-
"""Generic exceptions for the Mantarray GUI."""
from typing import Union


class MultiprocessingNotSetToSpawnError(Exception):
    def __init__(self, start_method: Union[str, None]):
        super().__init__(
            f"The multiprocessing start type has not been set to spawn, which is the only option on Windows. It is current set as '{start_method}'"
        )


class UnrecognizedDebugConsoleCommandError(Exception):
    pass


class UnrecognizedCommTypeFromMainToOKCommError(Exception):
    pass


class UnrecognizedAcquisitionManagerCommandError(Exception):
    pass


class UnrecognizedCommandFromMainToFileWriterError(Exception):
    pass


class UnrecognizedCommTypeFromMainToDataAnalyzerError(Exception):
    pass


class UnrecognizedDataFrameFormatNameError(Exception):
    pass


class LocalServerPortAlreadyInUseError(Exception):
    pass


class InvalidDataTypeFromOkCommError(TypeError):
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


class UnrecognizedMantarrayNamingCommandError(Exception):
    pass


class ImproperlyFormattedCustomerAccountUUIDError(Exception):
    pass


class ImproperlyFormattedUserAccountUUIDError(Exception):
    pass


class RecordingFolderDoesNotExistError(Exception):
    pass


class FirmwareFileNameDoesNotMatchWireOutVersionError(Exception):
    pass


class BarcodeNotClearedError(Exception):
    pass


class BarcodeScannerNotRespondingError(Exception):
    pass
