# -*- coding: utf-8 -*-
from mantarray_desktop_app.utils import CommandTracker
import pytest


def test_CommandTracker__converts_to_bool_correctly():
    ct = CommandTracker()

    assert not ct
    ct.add(0, {})
    assert ct
    ct.pop(0)
    assert not ct


def test_CommandTracker_pop__raises_correct_error_when_packet_type_not_present__packet_type_never_added():
    test_packet_type = 0

    with pytest.raises(ValueError, match=f"No commands of packet type: {test_packet_type}"):
        CommandTracker().pop(test_packet_type)


def test_CommandTracker_pop__raises_correct_error_when_packet_type_not_present__last_command_removed():
    ct = CommandTracker()

    test_packet_type = 0

    ct.add(test_packet_type, {})
    ct.pop(test_packet_type)

    with pytest.raises(ValueError):
        ct.pop(test_packet_type)


def test_CommandTracker_oldest__raises_correct_error_when_empty__no_commands_ever_added():
    with pytest.raises(IndexError, match="tracker is empty"):
        CommandTracker().oldest()


def test_CommandTracker_oldest__raises_correct_error_when_empty__last_item_removed():
    ct = CommandTracker()

    test_packet_type = 0

    ct.add(test_packet_type, {})
    ct.pop(test_packet_type)

    with pytest.raises(IndexError):
        ct.oldest()


def test_CommandTracker__tracks_and_updates_correctly__with_single_packet_type():
    ct = CommandTracker()

    test_packet_type = 1

    command_1 = {"key1": "val1"}
    command_2 = {"key2": "val2"}
    command_3 = {"key3": "val3"}
    command_4 = {"key4": "val4"}

    ct.add(test_packet_type, command_1)
    assert ct.oldest() == command_1
    ct.add(test_packet_type, command_2)
    assert ct.oldest() == command_1
    ct.add(test_packet_type, command_3)
    assert ct.oldest() == command_1

    assert ct.pop(test_packet_type) == command_1
    assert ct.oldest() == command_2

    ct.add(test_packet_type, command_4)
    assert ct.oldest() == command_2

    assert ct.pop(test_packet_type) == command_2
    assert ct.oldest() == command_3
    assert ct.pop(test_packet_type) == command_3
    assert ct.oldest() == command_4
    assert ct.pop(test_packet_type) == command_4


def test_CommandTracker__tracks_and_updates_correctly__with_multiple_packet_types():
    ct = CommandTracker()

    test_packet_type_a = 1
    test_packet_type_b = 2

    command_a1 = {"key1": "val1"}
    command_a2 = {"key2": "val2"}
    command_b1 = {"key3": "val3"}
    command_b2 = {"key4": "val4"}

    ct.add(test_packet_type_a, command_a1)
    assert ct.oldest() == command_a1
    ct.add(test_packet_type_b, command_b1)
    assert ct.oldest() == command_a1
    ct.add(test_packet_type_a, command_a2)
    assert ct.oldest() == command_a1

    assert ct.pop(test_packet_type_a) == command_a1
    assert ct.oldest() == command_b1

    ct.add(test_packet_type_b, command_b2)
    assert ct.oldest() == command_b1

    assert ct.pop(test_packet_type_a) == command_a2
    assert ct.oldest() == command_b1
    assert ct.pop(test_packet_type_b) == command_b1
    assert ct.oldest() == command_b2
    assert ct.pop(test_packet_type_b) == command_b2
