# -*- coding: utf-8 -*-
from mantarray_desktop_app import utils
import numpy as np


def test_convert_request_args_to_config_dict__calls_validate_settings(mocker):
    spied_validate = mocker.spy(utils, "validate_settings")
    input_dict = {"customer_account_uuid": "6613bf2b-7233-4b94-8f98-86172d315d64"}
    utils.convert_request_args_to_config_dict(input_dict)
    spied_validate.assert_called_once_with(input_dict)
