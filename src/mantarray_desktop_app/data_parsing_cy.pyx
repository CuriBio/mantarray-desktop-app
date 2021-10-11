# distutils: language = c++
# cython: language_level=3
# Tanner (9/1/20): Make sure to set `linetrace=False` except when profiling cython code or creating annotation file. All performance tests should be timed without line tracing enabled. Cython files in this package can easily be recompiled with `pip install -e .`
# cython: linetrace=False
"""Parsing data from Mantarray Hardware."""
from libcpp.map cimport map
from typing import List
from typing import Tuple

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE
from .constants import SERIAL_COMM_ADDITIONAL_BYTES_INDEX
from .constants import SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
from .constants import SERIAL_COMM_MAIN_MODULE_ID
from .constants import SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES
from .constants import SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
from .constants import SERIAL_COMM_NUM_SENSORS_PER_WELL
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


# Tanner (5/26/21): Can't import these constants from python and use them in array declarations, so have to redefine here
DEF MAGIC_WORD_LEN = 8
DEF TIME_INDEX_LEN = 8
DEF NUM_CHANNELS_PER_SENSOR = 3

# these values exist only for importing the constants defined above into the python test suite
SERIAL_COMM_MAGIC_WORD_LENGTH_BYTES_CY = MAGIC_WORD_LEN
SERIAL_COMM_TIME_INDEX_LENGTH_BYTES_CY = TIME_INDEX_LEN
SERIAL_COMM_NUM_CHANNELS_PER_SENSOR_CY = NUM_CHANNELS_PER_SENSOR

# convert python constants to C types
cdef char[MAGIC_WORD_LEN + 1] MAGIC_WORD = SERIAL_COMM_MAGIC_WORD_BYTES + bytes(1)
cdef int MIN_PACKET_SIZE = SERIAL_COMM_MIN_FULL_PACKET_LENGTH_BYTES

cdef int SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES_C_INT = SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES
cdef int SERIAL_COMM_NUM_CHANNELS_PER_SENSOR_C_INT = NUM_CHANNELS_PER_SENSOR
cdef int SERIAL_COMM_NUM_SENSORS_PER_WELL_C_INT = SERIAL_COMM_NUM_SENSORS_PER_WELL

cdef int SERIAL_COMM_MAIN_MODULE_ID_C_INT = SERIAL_COMM_MAIN_MODULE_ID
cdef int SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT = SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
cdef int SERIAL_COMM_ADDITIONAL_BYTES_INDEX_C_INT = SERIAL_COMM_ADDITIONAL_BYTES_INDEX


cdef packed struct SensorData:
    uint16_t time_offset
    int16_t data_points[NUM_CHANNELS_PER_SENSOR]


cdef packed struct Packet:
    char magic[MAGIC_WORD_LEN]
    uint16_t packet_len
    uint64_t timestamp
    uint8_t module_id
    uint8_t packet_type
    uint8_t time_index[TIME_INDEX_LEN]
    SensorData data


def handle_data_packets(
    unsigned char [:] read_bytes, list active_channels_list, uint64_t base_global_time
) -> Tuple[NDArray, NDArray, NDArray, int, List[Tuple[int, int, int, bytearray]], bytearray]:
    """Read the given number of data packets from the instrument.

    If data stream is interrupted by a packet that is not part of the data stream,
    a tuple of info about the interrupting packet will be returned and the first two data arrays will not be full.

    Args:
        read_bytes: an array of all bytes waiting to be parsed. Not gauranteed to all be bytes in a data packet
        active_channels_list: a list containing the number of channels on each active sensor, in order.

    Returns:
        A tuple of the array of parsed time indices, the array of time offsets, the array of parsed data, the number of data packets read, list of tuples containing info about interrupting packets if any occured (timestamp, module ID, packet type, and packet body bytes), the remaining unread bytes
    """
    read_bytes = read_bytes.copy()  # make sure data is C contiguous
    cdef int num_bytes = len(read_bytes)

    # convert active_channels_list to an array for faster indexing later
    active_channels_list_arr = np.array(active_channels_list, dtype=np.uint8, order="C")
    cdef uint8_t [:] active_channels_list_view = active_channels_list_arr

    cdef int num_wells = 24
    cdef int num_sensors = len(active_channels_list_view)
    cdef int num_time_offsets = num_sensors
    cdef int num_data_channels = sum(active_channels_list_view)
    cdef int data_packet_len = (
        MIN_PACKET_SIZE
        + num_data_channels * 2
        + num_sensors * SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES_C_INT
        + TIME_INDEX_LEN
    )
    cdef int num_data_packets_possible = num_bytes // data_packet_len

    # return values
    time_indices = np.empty(num_data_packets_possible, dtype=np.uint64, order="C")
    time_offsets = np.empty((num_time_offsets, num_data_packets_possible), dtype=np.uint16, order="C")
    data = np.empty((num_data_channels, num_data_packets_possible), dtype=np.int16, order="C")
    cdef int data_packet_idx = 0  # also represents numbers of data packets read. Will not increment after reading a "non-data" packet
    other_packet_info = list()

    # get memory views of numpy arrays for faster operations
    cdef uint64_t [::1] time_indices_view = time_indices
    cdef uint16_t [:, ::1] time_offsets_view = time_offsets
    cdef int16_t [:, ::1] data_view = data

    cdef unsigned int crc, original_crc
    cdef char[MAGIC_WORD_LEN + 1] magic_word
    magic_word[MAGIC_WORD_LEN] = 0

    cdef Packet *p
    cdef int time_offset_arr_idx
    cdef int channel_arr_idx
    cdef SensorData * sensor_data_ptr
    cdef int sensor
    cdef int num_channels_on_sensor
    cdef int channel
    cdef int bytes_idx = 0
    while bytes_idx <= num_bytes - MIN_PACKET_SIZE:
        # print("data_packet_idx:", data_packet_idx)
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
            print("PACKET TYPE:", p.packet_type)
            # raising error here, so ok to incur reasonable amount of python overhead here
            full_data_packet = bytearray(read_bytes[bytes_idx : bytes_idx + p.packet_len + 10])
            raise SerialCommIncorrectChecksumFromInstrumentError(
                f"Checksum Received: {original_crc}, Checksum Calculated: {crc}, Full Data Packet: {str(full_data_packet)}"
            )

        # if this packet was not a data packet then need to store its info and handle it after all data packets are parsed
        if (
            p.module_id != SERIAL_COMM_MAIN_MODULE_ID_C_INT
            or p.packet_type != SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT
        ):
            # exceptional case, so ok to incur reasonable amount of python overhead here
            other_bytes = bytearray(
                read_bytes[
                    bytes_idx + SERIAL_COMM_ADDITIONAL_BYTES_INDEX_C_INT : bytes_idx + p.packet_len + 6
                ]
            )
            other_packet_info.append((p.timestamp, p.module_id, p.packet_type, other_bytes))
            bytes_idx += p.packet_len + 10
            continue

        # add to time index array
        time_indices_view[data_packet_idx] = (<uint64_t *> &p.time_index)[0] - base_global_time
        # add next data points to data array
        sensor_data_ptr = &p.data
        channel_arr_idx = 0
        time_offset_arr_idx = 0
        for sensor in range(num_sensors):
            time_offsets_view[time_offset_arr_idx, data_packet_idx] = sensor_data_ptr.time_offset
            time_offset_arr_idx += 1
            num_channels_on_sensor = active_channels_list_view[sensor]
            for channel in range(num_channels_on_sensor):
                data_view[channel_arr_idx, data_packet_idx] = sensor_data_ptr.data_points[channel]
                channel_arr_idx += 1
            # shift SensorData ptr by appropriate amount
            sensor_data_ptr = <SensorData *> (
                (<uint8_t *> sensor_data_ptr)
                + SERIAL_COMM_TIME_OFFSET_LENGTH_BYTES_C_INT
                + (num_channels_on_sensor * 2)
            )
        # increment idxs
        data_packet_idx += 1
        bytes_idx += data_packet_len

    return (
        time_indices,
        time_offsets,
        data,
        data_packet_idx,
        other_packet_info,
        bytearray(read_bytes[bytes_idx:]),
    )
