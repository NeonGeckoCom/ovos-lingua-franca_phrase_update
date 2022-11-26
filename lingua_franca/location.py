# Copyright 2020 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific location governing permissions and
# limitations under the License.
#
from enum import Enum

__default_location = "US"  # Kansas is the default default location
__latitude = 38.971669
__longitude = -95.23525


class Hemisphere(Enum):
    NORTH = 0
    SOUTH = 1


def get_active_location():
    """ Get the default location

    Returns:
        (float, floats): latitude, longitude tuple
    """
    return __latitude, __longitude


def set_active_location(code=None, lat=None, lon=None):
    """ Set the default location to be used in location aware
    formatting/parsing

    Args:
        code (str): ISO location code, e.g. "US" or "PT"
        lat (float): latitude
        lon (float): longitude
    """
    global __default_location, __longitude, __latitude
    if code and __default_location != code:
        # TODO: Validate location codes?
        __default_location = code
    if lon:
        __longitude = lon
    if lat:
        __latitude = lat


def get_active_location_code():
    """ Get the default location ISO code

    Returns:
        (str): A ISO location code, e.g. ("US", "PT", "BR", or "UK")
    """

    return __default_location


def get_active_hemisphere():
    """ Get the default location

    Returns:
        (float, floats): latitude, longitude tuple
    """
    if __latitude < 0:
        return Hemisphere.SOUTH
    return Hemisphere.NORTH
