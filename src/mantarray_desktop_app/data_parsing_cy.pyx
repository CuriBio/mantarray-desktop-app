# distutils: language = c++
# cython: language_level=3
# Tanner (9/1/20): Make sure to set `linetrace=False` except when profiling cython code or creating annotation file. All performance tests should be timed without line tracing enabled. Cython files in this package can easily be recompiled with `pip install -e .`
# cython: linetrace=False
"""Parsing data from Mantarray Hardware."""
from libcpp.map cimport map
from typing import Optional
from typing import Tuple

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX,SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from .exceptions import SerialCommIncorrectChecksumFromInstrumentError
from .exceptions import SerialCommIncorrectMagicWordFromMantarrayError

# Beta 1

cdef map[int, map[int, int]] ADC_CH_TO_24_WELL_INDEX_C_MAP = dict(ADC_CH_TO_24_WELL_INDEX)
cdef map[int, map[int, bint]] ADC_CH_TO_IS_REF_SENSOR_C_MAP = dict(ADC_CH_TO_IS_REF_SENSOR)
cdef int RAW_TO_SIGNED_CONVERSION_VALUE_C_INT = RAW_TO_SIGNED_CONVERSION_VALUE


def parse_sensor_bytes(unsigned char[4] data_bytes) -> Tuple[bool, int, int]:
    """Parse the 32 bits of data related to a sensor reading.

    Assumes for now that the sensor/channel address will be the right-most 8-bits in the bytearray, and that everything is little-endian.

    All odd adc channel numbers indicate a reference sensor.

    Returns:
        true if a reference sensor, the index of the reference sensor or plate well index of construct sensor, and the value in the 24-bits
    """
    # TODO Tanner (2/17/21): investigate pybind
    # TODO Tanner (2/17/21): investigate wrap around and bounce
    cdef int meta_data_byte, adc_num, adc_ch_num, index
    cdef bint is_reference_sensor

    meta_data_byte = int(data_bytes[0])
    adc_num, adc_ch_num, _ = parse_adc_metadata_byte(meta_data_byte)

    is_reference_sensor = ADC_CH_TO_IS_REF_SENSOR_C_MAP[adc_num][adc_ch_num]
    index = (
        adc_num if is_reference_sensor else <int> ADC_CH_TO_24_WELL_INDEX_C_MAP[adc_num][adc_ch_num]
    )

    cdef unsigned char[3] little_endian_int24
    cdef int i
    for i in range(3):
        little_endian_int24[i] = data_bytes[i + 1]

    cdef int sensor_value = parse_little_endian_int24(little_endian_int24)
    cdef int signed_value = sensor_value - RAW_TO_SIGNED_CONVERSION_VALUE_C_INT
    return is_reference_sensor, index, signed_value


cpdef (int, int, bint) parse_adc_metadata_byte(int metadata_byte):
    """Convert the metadata byte from the ADC to formatted data.

    Returns:
        A tuple of the ADC number, the channel number of that ADC, and the value of the error bit
    """
    cdef int adc_num, adc_ch_num
    cdef bint error

    adc_num = (metadata_byte & 0xF0) >> 4
    error = (metadata_byte & 0x08) >> 3
    adc_ch_num = metadata_byte & 0x07
    return adc_num, adc_ch_num, error


cpdef int parse_little_endian_int24(unsigned char[3] data_bytes):
    """Convert 3 elements of a little-endian byte array into an int."""
    cdef int value = data_bytes[0] + (data_bytes[1] << 8) + (data_bytes[2] << 16)
    return value


# Beta 2
from libc.stdint cimport int16_t
from libc.stdint cimport uint8_t
from libc.stdint cimport uint16_t
from libc.stdint cimport uint32_t
from libc.stdint cimport uint64_t
from libc.string cimport strncpy
from libc.string cimport strncmp
from nptyping import NDArray
# import numpy correctly
import numpy as np
cimport numpy as np
np.import_array()

cdef extern from "../zlib/zlib.h":
    ctypedef unsigned char Bytef
    ctypedef unsigned long uLong
    ctypedef unsigned int uInt

    uLong crc32(uLong, Bytef*, uInt)
    Bytef* Z_NULL


cdef char[9] MAGIC_WORD = SERIAL_COMM_MAGIC_WORD_BYTES + bytes(1)
cdef int MAGIC_WORD_LEN = len(SERIAL_COMM_MAGIC_WORD_BYTES)  # 8
cdef int SERIAL_COMM_TIME_INDEX_LENGTH_BYTES_C_INT = SERIAL_COMM_TIME_INDEX_LENGTH_BYTES
cdef int SERIAL_COMM_MAIN_MODULE_ID_C_INT = SERIAL_COMM_MAIN_MODULE_ID
cdef int SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT = SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
cdef int SERIAL_COMM_ADDITIONAL_BYTES_INDEX_C_INT = SERIAL_COMM_ADDITIONAL_BYTES_INDEX
cdef int MIN_PACKET_SIZE = SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES

cdef packed struct Packet:
    char magic[8]
    uint16_t packet_len
    uint64_t timestamp
    uint8_t module_id
    uint8_t packet_type
    uint32_t time_index
    int16_t data


def handle_data_packets(
    unsigned char[:] read_bytes, int data_packet_len
) -> Tuple[NDArray, NDArray, int, Optional[Tuple[int, int, int, bytearray]], Optional[bytearray]]:
    """Read the given number of data packets from the instrument.

    If data stream is interrupted by a packet that is not part of the data stream,
    a tuple of info about the interrupting packet will be returned and the first two data arrays will not be full.

    Args:
        read_bytes: an array of all bytes waiting to be parsed. Not gauranteed to all be bytes in a data packet
        data_packet_len: the length of a data packet

    Returns:
        A tuple of the array of parsed time indices, the array of parsed data, the number of data packets read, optional tuple containing info about the interrupting packet if one occured (timestamp, module ID, packet type, and packet body bytes), the remaining unread bytes
    """
    # make sure data is C contiguous
    read_bytes = read_bytes.copy()

    cdef int num_bytes = len(read_bytes)
    cdef int num_data_packets_possible = num_bytes // data_packet_len
    cdef int num_data_channels = (
        data_packet_len - MIN_PACKET_SIZE - SERIAL_COMM_TIME_INDEX_LENGTH_BYTES_C_INT
    ) // 2

    cdef Packet *p

    # return values
    cdef np.ndarray[np.uint64_t, ndim=1] time_indices = np.empty(num_data_packets_possible, dtype=np.uint64)
    cdef np.ndarray[np.int16_t, ndim=2] data = np.empty((num_data_channels, num_data_packets_possible), dtype=np.int16)
    cdef int data_packet_idx = 0  # also represents numbers of data packets read. Will not increment after reading a "non-data" packet
    other_packet_info = None

    cdef unsigned int crc, original_crc
    cdef char[9] magic_word
    magic_word[8] = 0

    cdef int bytes_idx = 0
    cdef int channel_num
    while bytes_idx <= num_bytes - MIN_PACKET_SIZE:
        p = <Packet *> &read_bytes[bytes_idx]

        # check that magic word is correct
        strncpy(magic_word, p.magic, MAGIC_WORD_LEN);
        if strncmp(magic_word, MAGIC_WORD, MAGIC_WORD_LEN) != 0:
            raise SerialCommIncorrectMagicWordFromMantarrayError(str(magic_word))

        # get actual CRC value from packet
        original_crc = (<uint32_t *> ((<uint8_t *> &p.time_index) + p.packet_len - 14))[0]
        # calculate expected CRC value
        crc = crc32(0, Z_NULL, 0)
        crc = crc32(crc, <uint8_t *> &p.magic, p.packet_len + 6)
        # check that actual CRC is the expected value. Do this before checking if it is a data packet
        if crc != original_crc:
            # raising error here, so ok to incur reasonable amount of python overhead here
            full_data_packet = bytearray(read_bytes[bytes_idx : bytes_idx + p.packet_len + 10])
            raise SerialCommIncorrectChecksumFromInstrumentError(
                f"Checksum Received: {original_crc}, Checksum Calculated: {crc}, Full Data Packet: {str(full_data_packet)}"
            )

        # if this packet was not a data packet then need to set optional return values, break out of loop, and return
        if (
            p.module_id != SERIAL_COMM_MAIN_MODULE_ID_C_INT
            or p.packet_type != SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT
        ):
            # breaking out of loop here, so ok to incur reasonable amount of python overhead here
            other_bytes = bytearray(
                read_bytes[
                    bytes_idx + SERIAL_COMM_ADDITIONAL_BYTES_INDEX_C_INT : bytes_idx + p.packet_len + 6
                ]
            )
            other_packet_info = (p.timestamp, p.module_id, p.packet_type, other_bytes)
            # increment bytes_idx here as it will be used when returning the unread bytes
            bytes_idx += p.packet_len + 10
            break

        # add to timestamp array
        time_indices[data_packet_idx] = p.time_index
        # add next data points to data array
        for channel_num in range(num_data_channels):
            data[channel_num, data_packet_idx] = (&p.data + channel_num)[0]
        # increment idxs
        data_packet_idx += 1
        bytes_idx += data_packet_len

    return (
        time_indices,
        data,
        data_packet_idx,
        other_packet_info,
        bytearray(read_bytes[bytes_idx:]),
    )
