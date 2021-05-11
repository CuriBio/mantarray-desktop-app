# distutils: language = c++
# cython: language_level=3
# Tanner (9/1/20): Make sure to set `linetrace=False` except when profiling cython code or creating annotation file. All performance tests should be timed without line tracing enabled. Cython files in this package can easily be recompiled with `pip install -e .`
# cython: linetrace=False
"""Parsing data from Mantarray Hardware."""
from libcpp.map cimport map
from typing import Tuple

from .constants import ADC_CH_TO_24_WELL_INDEX, SERIAL_COMM_MAGIC_WORD_BYTES
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE

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

from libc.stdint cimport uint8_t
from libc.stdint cimport uint16_t
from libc.stdint cimport int16_t
from libc.stdint cimport uint64_t
from nptyping import NDArray
# import numpy correctly
import numpy as np
cimport numpy as np
np.import_array()


cdef int MAGIC_WORD_LEN = len(SERIAL_COMM_MAGIC_WORD_BYTES)
cdef int SERIAL_COMM_MAIN_MODULE_ID_C_INT = SERIAL_COMM_MAIN_MODULE_ID
cdef int SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT = SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE
cdef int MIN_PACKET_SIZE = 24

cdef struct Packet:
    unsigned char magic[8]
    uint16_t packet_len
    uint8_t timestamp[8]  # Tanner (5/10/21): uint64_t can only align to mem addr divisible by 8, so have to use uint8_t here and cast later
    uint8_t module_id
    uint8_t packet_type
    int16_t data


def handle_data_packets(unsigned char[:] read_bytes, int data_packet_len) -> Tuple[NDArray, NDArray, int, bytes, bytes]:
    """Read the given number of data packets from the instrument.

    If data stream is interrupted by packet that is not part of the data stream,
    the packet bytes will be returned and the data arrays will not be full.

    Args:
        read_bytes: an array of all bytes waiting to be parsed. Not gauranteed to all be bytes in a data packet
        data_packet_len: the length of a data packet

    Returns:
        A tuple of the array of parsed timestamps, the array of parsed data, the number of data packets read, the bytes from the packet body of an interrupting packet from the instrument (will be empty if one was not read), the remaining unread bytes
    """
    read_bytes = read_bytes.copy()

    cdef int data_packet_idx = 0
    cdef int bytes_idx = 0

    cdef int num_bytes = len(read_bytes)
    cdef int num_data_packets_possible = num_bytes // data_packet_len
    cdef int num_data_channels = (data_packet_len - MIN_PACKET_SIZE) // 2
    # print(num_data_channels, num_data_points_per_channel)

    cdef uint64_t ts
    cdef Packet *p

    cdef np.ndarray[np.uint64_t, ndim=1] timestamps = np.empty(num_data_packets_possible, dtype=np.uint64)
    cdef np.ndarray[np.int16_t, ndim=2] data = np.empty((num_data_channels, num_data_packets_possible), dtype=np.int16)

    cdef int channel_num
    while bytes_idx <= num_bytes - data_packet_len:
        p = <Packet *> &read_bytes[bytes_idx]

        ts = (<uint64_t *> &p.timestamp[0])[0]
        timestamps[data_packet_idx] = ts

        # if p.module_id != SERIAL_COMM_MAIN_MODULE_ID_C_INT:
        #     break
        # elif p.packet_type != SERIAL_COMM_MAGNETOMETER_DATA_PACKET_TYPE_C_INT:
        #     break

        for channel_num in range(num_data_channels):
            data[channel_num, data_packet_idx] = (&p.data + channel_num)[0]
        data_packet_idx += 1
        bytes_idx += data_packet_len

    # TODO test crc32. should also check crc 32 of packets that aren't data packets
    return (
        timestamps,
        data,
        data_packet_idx,
        bytes(0),
        bytes(0)
    )



# cpdef (int, unsigned char, unsigned char) get_data_packet(read_func, char[:] data_buf):
#     """Read the next packet from the instrument. Load the packet body in the char buffer given

#     Args:
#         read_func: a pointer to the read function of the instrument's serial interface
#         data_buf: a buffer to load the packet body into

#     Returns:
#         The timestamp, module ID, and packet type of the data packet
#     """
#     magic_word_bytes = read_func(size=MAGIC_WORD_LEN)  # TODO check this value
#     packet_length_bytes = read_func(size=2)
#     packet_length = int.from_bytes(packet_size_bytes, byteorder="little")
#     cdef char[:] read_bytes = bytearray(read_func(size=packet_length))[:]


#     data_buf[:] = read_bytes[:]
#     return 0,0,0
