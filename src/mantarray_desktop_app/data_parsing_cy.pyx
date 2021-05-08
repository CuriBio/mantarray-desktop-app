# distutils: language = c++
# cython: language_level=3
# Tanner (9/1/20): Make sure to set `linetrace=False` except when profiling cython code or creating annotation file. All performance tests should be timed without line tracing enabled. Cython files in this package can easily be recompiled with `pip install -e .`
# cython: linetrace=True
"""Parsing data from Mantarray Hardware."""
from libcpp.map cimport map
from typing import Tuple
from nptyping import NDArray

from .constants import ADC_CH_TO_24_WELL_INDEX
from .constants import ADC_CH_TO_IS_REF_SENSOR
from .constants import RAW_TO_SIGNED_CONVERSION_VALUE

cdef map[int, map[int, int]] ADC_CH_TO_24_WELL_INDEX_C_MAP = dict(ADC_CH_TO_24_WELL_INDEX)
cdef map[int, map[int, bint]] ADC_CH_TO_IS_REF_SENSOR_C_MAP = dict(ADC_CH_TO_IS_REF_SENSOR)
cdef int RAW_TO_SIGNED_CONVERSION_VALUE_C_INT = RAW_TO_SIGNED_CONVERSION_VALUE


# Beta 1 functions

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


# Beta 2 functions

def read_data_packets(read_func, int num_packets_to_read, int num_channels_enabled) -> Tuple[NDArray, NDArray, int, bytes]:
    """Read the given number of data packets from the instrument.

    If data stream is interrupted by packet that is not part of the data stream,
    the packet bytes will be returned and the data arrays will not be full.

    Args:
        read_func: a pointer to the read function of the instrument's serial interface
        num_packets_to_read: the desired number of packets to read
        num_channels_enabled: the number of data channels (sensors/axes) enabled

    Returns:
        A tuple of the array of parsed timestamps, the array of parsed data, the number of data packets read, and the bytes of an interrupting packet from the instrument (will be empty if one was not read)
    """
    pass


cpdef (int, unsigned char, unsigned char) get_data_packet(read_func, char[:] data_buf):
    """Read the next packet from the instrument. Load the packet body in the char buffer given

    Args:
        read_func: a pointer to the read function of the instrument's serial interface
        data_buf: a buffer to load the packet body into

    Returns:
        The timestamp, module ID, and packet type of the data packet
    """
    cdef char[:] a = bytearray(read_func(size=3))[:]
    data_buf[:] = a[:]
