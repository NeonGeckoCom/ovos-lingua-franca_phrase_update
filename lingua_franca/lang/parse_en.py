#
# Copyright 2017 Mycroft AI Inc.
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
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
import re
from datetime import datetime, timedelta, time

from dateutil.relativedelta import relativedelta

from lingua_franca.internal import resolve_resource_file
from lingua_franca.lang.common_data_en import _ARTICLES_EN, _LONG_ORDINAL_EN, _LONG_SCALE_EN, _SHORT_SCALE_EN, \
    _SHORT_ORDINAL_EN, \
    _NEGATIVES_EN, _SUMS_EN, _MULTIPLIES_LONG_SCALE_EN, \
    _MULTIPLIES_SHORT_SCALE_EN, _FRACTION_MARKER_EN, _DECIMAL_MARKER_EN, \
    _STRING_NUM_EN, _STRING_SHORT_ORDINAL_EN, _STRING_LONG_ORDINAL_EN, \
    _generate_plurals_en, _SPOKEN_EXTRA_NUM_EN
from lingua_franca.lang.parse_common import is_numeric, look_for_fractions, \
    invert_dict, ReplaceableNumber, partition_list, tokenize, Token, Normalizer
from lingua_franca.time import now_local
from dateutil.easter import easter
from datetime import timedelta, datetime, date, time
from holidays import CountryHoliday
from lingua_franca.lang.parse_common import DurationResolution, invert_dict, \
    ReplaceableNumber, partition_list, tokenize, Token, Normalizer, Season, \
    DateTimeResolution, is_numeric, look_for_fractions
from lingua_franca.lang.common_data_en import _ARTICLES_EN, _NUM_STRING_EN, \
    _LONG_ORDINAL_EN, _LONG_SCALE_EN, _SHORT_SCALE_EN, _SHORT_ORDINAL_EN, \
    _SEASONS_EN, _HEMISPHERES_EN, _ORDINAL_BASE_EN, _NAMED_ERAS_EN

import re
import json
import math
from lingua_franca import resolve_resource_file
from lingua_franca.time import date_to_season, season_to_date, \
    get_season_range, next_season_date, last_season_date, get_date_ordinal, \
    get_weekend_range, get_week_range, get_century_range, \
    get_millennium_range, get_year_range, get_month_range, get_decade_range, \
    weekday_to_int, month_to_int, now_local, DAYS_IN_1_YEAR, DAYS_IN_1_MONTH
from lingua_franca.location import Hemisphere, get_active_hemisphere, \
    get_active_location, get_active_location_code

try:
    from simple_NER.annotators.locations import LocationNER

    _ner = LocationNER()
except ImportError:
    _ner = None
    print("Location extraction disabled")
    print("Run pip install simple_NER>=0.4.1")


def _convert_words_to_numbers_en(text, short_scale=True, ordinals=False):
    """
    Convert words in a string into their equivalent numbers.
    Args:
        text str:
        short_scale boolean: True if short scale numbers should be used.
        ordinals boolean: True if ordinals (e.g. first, second, third) should
                          be parsed to their number values (1, 2, 3...)

    Returns:
        str
        The original text, with numbers subbed in where appropriate.

    """
    tokens = tokenize(text)
    numbers_to_replace = \
        _extract_numbers_with_text_en(tokens, short_scale, ordinals)
    numbers_to_replace.sort(key=lambda number: number.start_index)

    results = []
    for token in tokens:
        if not numbers_to_replace or \
                token.index < numbers_to_replace[0].start_index:
            results.append(token.word)
        else:
            if numbers_to_replace and \
                    token.index == numbers_to_replace[0].start_index:
                results.append(str(numbers_to_replace[0].value))
            if numbers_to_replace and \
                    token.index == numbers_to_replace[0].end_index:
                numbers_to_replace.pop(0)

    return ' '.join(results)


def _extract_numbers_with_text_en(tokens, short_scale=True,
                                  ordinals=False, fractional_numbers=True):
    """
    Extract all numbers from a list of Tokens, with the words that
    represent them.

    Args:
        [Token]: The tokens to parse.
        short_scale bool: True if short scale numbers should be used, False for
                          long scale. True by default.
        ordinals bool: True if ordinal words (first, second, third, etc) should
                       be parsed.
        fractional_numbers bool: True if we should look for fractions and
                                 decimals.

    Returns:
        [ReplaceableNumber]: A list of tuples, each containing a number and a
                         string.

    """
    placeholder = "<placeholder>"  # inserted to maintain correct indices
    results = []
    while True:
        to_replace = \
            _extract_number_with_text_en(tokens, short_scale,
                                         ordinals, fractional_numbers)

        if not to_replace:
            break

        results.append(to_replace)

        tokens = [
            t if not
            to_replace.start_index <= t.index <= to_replace.end_index
            else
            Token(placeholder, t.index) for t in tokens
        ]
    results.sort(key=lambda n: n.start_index)
    return results


def _extract_number_with_text_en(tokens, short_scale=True,
                                 ordinals=False, fractional_numbers=True):
    """
    This function extracts a number from a list of Tokens.

    Args:
        tokens str: the string to normalize
        short_scale (bool): use short scale if True, long scale if False
        ordinals (bool): consider ordinal numbers, third=3 instead of 1/3
        fractional_numbers (bool): True if we should look for fractions and
                                   decimals.
    Returns:
        ReplaceableNumber

    """
    number, tokens = \
        _extract_number_with_text_en_helper(tokens, short_scale,
                                            ordinals, fractional_numbers)
    while tokens and tokens[0].word in _ARTICLES_EN:
        tokens.pop(0)
    return ReplaceableNumber(number, tokens)


def _extract_number_with_text_en_helper(tokens,
                                        short_scale=True, ordinals=False,
                                        fractional_numbers=True):
    """
    Helper for _extract_number_with_text_en.

    This contains the real logic for parsing, but produces
    a result that needs a little cleaning (specific, it may
    contain leading articles that can be trimmed off).

    Args:
        tokens [Token]:
        short_scale boolean:
        ordinals boolean:
        fractional_numbers boolean:

    Returns:
        int or float, [Tokens]

    """
    if fractional_numbers:
        fraction, fraction_text = \
            _extract_fraction_with_text_en(tokens, short_scale, ordinals)
        if fraction:
            return fraction, fraction_text

        decimal, decimal_text = \
            _extract_decimal_with_text_en(tokens, short_scale, ordinals)
        if decimal:
            return decimal, decimal_text

    return _extract_whole_number_with_text_en(tokens, short_scale, ordinals)


def _extract_fraction_with_text_en(tokens, short_scale, ordinals):
    """
    Extract fraction numbers from a string.

    This function handles text such as '2 and 3/4'. Note that "one half" or
    similar will be parsed by the whole number function.

    Args:
        tokens [Token]: words and their indexes in the original string.
        short_scale boolean:
        ordinals boolean:

    Returns:
        (int or float, [Token])
        The value found, and the list of relevant tokens.
        (None, None) if no fraction value is found.

    """
    for c in _FRACTION_MARKER_EN:
        partitions = partition_list(tokens, lambda t: t.word == c)

        if len(partitions) == 3:
            numbers1 = \
                _extract_numbers_with_text_en(partitions[0], short_scale,
                                              ordinals,
                                              fractional_numbers=False)
            numbers2 = \
                _extract_numbers_with_text_en(partitions[2], short_scale,
                                              ordinals,
                                              fractional_numbers=True)

            if not numbers1 or not numbers2:
                return None, None

            # ensure first is not a fraction and second is a fraction
            num1 = numbers1[-1]
            num2 = numbers2[0]
            if num1.value >= 1 and 0 < num2.value < 1:
                return num1.value + num2.value, \
                       num1.tokens + partitions[1] + num2.tokens

    return None, None


def _extract_decimal_with_text_en(tokens, short_scale, ordinals):
    """
    Extract decimal numbers from a string.

    This function handles text such as '2 point 5'.

    Notes:
        While this is a helper for extractnumber_en, it also depends on
        extractnumber_en, to parse out the components of the decimal.

        This does not currently handle things like:
            number dot number number number

    Args:
        tokens [Token]: The text to parse.
        short_scale boolean:
        ordinals boolean:

    Returns:
        (float, [Token])
        The value found and relevant tokens.
        (None, None) if no decimal value is found.

    """
    for c in _DECIMAL_MARKER_EN:
        partitions = partition_list(tokens, lambda t: t.word == c)

        if len(partitions) == 3:
            numbers1 = \
                _extract_numbers_with_text_en(partitions[0], short_scale,
                                              ordinals,
                                              fractional_numbers=False)
            numbers2 = \
                _extract_numbers_with_text_en(partitions[2], short_scale,
                                              ordinals,
                                              fractional_numbers=False)

            if not numbers1 or not numbers2:
                return None, None

            number = numbers1[-1]
            decimal = numbers2[0]

            # TODO handle number dot number number number
            if "." not in str(decimal.text):
                return number.value + float('0.' + str(decimal.value)), \
                       number.tokens + partitions[1] + decimal.tokens
    return None, None


def _extract_whole_number_with_text_en(tokens, short_scale, ordinals):
    """
    Handle numbers not handled by the decimal or fraction functions. This is
    generally whole numbers. Note that phrases such as "one half" will be
    handled by this function, while "one and a half" are handled by the
    fraction function.

    Args:
        tokens [Token]:
        short_scale boolean:
        ordinals boolean:

    Returns:
        int or float, [Tokens]
        The value parsed, and tokens that it corresponds to.

    """
    multiplies, string_num_ordinal, string_num_scale = \
        _initialize_number_data_en(short_scale, speech=ordinals is not None)

    number_words = []  # type: [Token]
    val = False
    prev_val = None
    next_val = None
    to_sum = []
    for idx, token in enumerate(tokens):
        current_val = None
        if next_val:
            next_val = None
            continue

        word = token.word.lower()
        if word in _ARTICLES_EN or word in _NEGATIVES_EN:
            number_words.append(token)
            continue

        prev_word = tokens[idx - 1].word.lower() if idx > 0 else ""
        next_word = tokens[idx + 1].word.lower() if idx + 1 < len(tokens) else ""

        if is_numeric(word[:-2]) and \
                (word.endswith("st") or word.endswith("nd") or
                 word.endswith("rd") or word.endswith("th")):

            # explicit ordinals, 1st, 2nd, 3rd, 4th.... Nth
            word = word[:-2]

            # handle nth one
            if next_word == "one":
                # would return 1 instead otherwise
                tokens[idx + 1] = Token("", idx)
                next_word = ""

        # TODO replaces the wall of "and" and "or" with all() or any() as
        #  appropriate, the whole codebase should be checked for this pattern
        if word not in string_num_scale and \
                word not in _STRING_NUM_EN and \
                word not in _SUMS_EN and \
                word not in multiplies and \
                not (ordinals and word in string_num_ordinal) and \
                not is_numeric(word) and \
                not is_fractional_en(word, short_scale=short_scale) and \
                not look_for_fractions(word.split('/')):
            words_only = [token.word for token in number_words]

            if number_words and not all([w.lower() in _ARTICLES_EN |
                                         _NEGATIVES_EN for w in words_only]):
                break
            else:
                number_words = []
                continue
        elif word not in multiplies \
                and prev_word not in multiplies \
                and prev_word not in _SUMS_EN \
                and not (ordinals and prev_word in string_num_ordinal) \
                and prev_word not in _NEGATIVES_EN \
                and prev_word not in _ARTICLES_EN:
            number_words = [token]

        elif prev_word in _SUMS_EN and word in _SUMS_EN:
            number_words = [token]
        elif ordinals is None and \
                (word in string_num_ordinal or word in _SPOKEN_EXTRA_NUM_EN):
            # flagged to ignore this token
            continue
        else:
            number_words.append(token)

        # is this word already a number ?
        if is_numeric(word):
            if word.isdigit():  # doesn't work with decimals
                val = int(word)
            else:
                val = float(word)
            current_val = val

        # is this word the name of a number ?
        if word in _STRING_NUM_EN:
            val = _STRING_NUM_EN.get(word)
            current_val = val
        elif word in string_num_scale:
            val = string_num_scale.get(word)
            current_val = val
        elif ordinals and word in string_num_ordinal:
            val = string_num_ordinal[word]
            current_val = val

        # is the prev word an ordinal number and current word is one?
        # second one, third one
        if ordinals and prev_word in string_num_ordinal and val == 1:
            val = prev_val

        # is the prev word a number and should we sum it?
        # twenty two, fifty six
        if (prev_word in _SUMS_EN and val and val < 10) or all([prev_word in
                                                                multiplies,
                                                                val < prev_val if prev_val else False]):
            val = prev_val + val

        # is the prev word a number and should we multiply it?
        # twenty hundred, six hundred
        if word in multiplies:
            if not prev_val:
                prev_val = 1
            val = prev_val * val

        # is this a spoken fraction?
        # half cup
        if val is False and \
                not (ordinals is None and word in string_num_ordinal):
            val = is_fractional_en(word, short_scale=short_scale,
                                   spoken=ordinals is not None)

            current_val = val

        # 2 fifths
        if ordinals is False:
            next_val = is_fractional_en(next_word, short_scale=short_scale)
            if next_val:
                if not val:
                    val = 1
                val = val * next_val
                number_words.append(tokens[idx + 1])

        # is this a negative number?
        if val and prev_word and prev_word in _NEGATIVES_EN:
            val = 0 - val

        # let's make sure it isn't a fraction
        if not val:
            # look for fractions like "2/3"
            aPieces = word.split('/')
            if look_for_fractions(aPieces):
                val = float(aPieces[0]) / float(aPieces[1])
                current_val = val

        else:
            if current_val and all([
                prev_word in _SUMS_EN,
                word not in _SUMS_EN,
                word not in multiplies,
                current_val >= 10]):
                # Backtrack - we've got numbers we can't sum.
                number_words.pop()
                val = prev_val
                break
            prev_val = val

            if word in multiplies and next_word not in multiplies:
                # handle long numbers
                # six hundred sixty six
                # two million five hundred thousand
                #
                # This logic is somewhat complex, and warrants
                # extensive documentation for the next coder's sake.
                #
                # The current word is a power of ten. `current_val` is
                # its integer value. `val` is our working sum
                # (above, when `current_val` is 1 million, `val` is
                # 2 million.)
                #
                # We have a dict `string_num_scale` containing [value, word]
                # pairs for "all" powers of ten: string_num_scale[10] == "ten.
                #
                # We need go over the rest of the tokens, looking for other
                # powers of ten. If we find one, we compare it with the current
                # value, to see if it's smaller than the current power of ten.
                #
                # Numbers which are not powers of ten will be passed over.
                #
                # If all the remaining powers of ten are smaller than our
                # current value, we can set the current value aside for later,
                # and begin extracting another portion of our final result.
                # For example, suppose we have the following string.
                # The current word is "million".`val` is 9000000.
                # `current_val` is 1000000.
                #
                #    "nine **million** nine *hundred* seven **thousand**
                #     six *hundred* fifty seven"
                #
                # Iterating over the rest of the string, the current
                # value is larger than all remaining powers of ten.
                #
                # The if statement passes, and nine million (9000000)
                # is appended to `to_sum`.
                #
                # The main variables are reset, and the main loop begins
                # assembling another number, which will also be appended
                # under the same conditions.
                #
                # By the end of the main loop, to_sum will be a list of each
                # "place" from 100 up: [9000000, 907000, 600]
                #
                # The final three digits will be added to the sum of that list
                # at the end of the main loop, to produce the extracted number:
                #
                #    sum([9000000, 907000, 600]) + 57
                # == 9,000,000 + 907,000 + 600 + 57
                # == 9,907,657
                #
                # >>> foo = "nine million nine hundred seven thousand six
                #            hundred fifty seven"
                # >>> extract_number(foo)
                # 9907657

                time_to_sum = True
                for other_token in tokens[idx + 1:]:
                    if other_token.word.lower() in multiplies:
                        if string_num_scale[other_token.word.lower()] >= current_val:
                            time_to_sum = False
                        else:
                            continue
                    if not time_to_sum:
                        break
                if time_to_sum:
                    to_sum.append(val)
                    val = 0
                    prev_val = 0

    if val is not None and to_sum:
        val += sum(to_sum)

    return val, number_words


def _initialize_number_data_en(short_scale, speech=True):
    """
    Generate dictionaries of words to numbers, based on scale.

    This is a helper function for _extract_whole_number.

    Args:
        short_scale (bool):
        speech (bool): consider extra words (_SPOKEN_EXTRA_NUM_EN) to be numbers

    Returns:
        (set(str), dict(str, number), dict(str, number))
        multiplies, string_num_ordinal, string_num_scale

    """
    multiplies = _MULTIPLIES_SHORT_SCALE_EN if short_scale \
        else _MULTIPLIES_LONG_SCALE_EN

    string_num_ordinal_en = _STRING_SHORT_ORDINAL_EN if short_scale \
        else _STRING_LONG_ORDINAL_EN

    string_num_scale_en = _SHORT_SCALE_EN if short_scale else _LONG_SCALE_EN
    string_num_scale_en = invert_dict(string_num_scale_en)
    string_num_scale_en.update(_generate_plurals_en(string_num_scale_en))

    if speech:
        string_num_scale_en.update(_SPOKEN_EXTRA_NUM_EN)
    return multiplies, string_num_ordinal_en, string_num_scale_en


def extract_number_en(text, short_scale=True, ordinals=False):
    """
    This function extracts a number from a text string,
    handles pronunciations in long scale and short scale

    https://en.wikipedia.org/wiki/Names_of_large_numbers

    Args:
        text (str): the string to normalize
        short_scale (bool): use short scale if True, long scale if False
        ordinals (bool): consider ordinal numbers, third=3 instead of 1/3
    Returns:
        (int) or (float) or False: The extracted number or False if no number
                                   was found

    """
    return _extract_number_with_text_en(tokenize(text.lower()),
                                        short_scale, ordinals).value


def extract_duration_en(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """
    Convert an english phrase into a number of seconds

    Convert things like:
        "10 minute"
        "2 and a half hours"
        "3 days 8 hours 10 minutes and 49 seconds"
    into an int, representing the total number of seconds.

    The words used in the duration will be consumed, and
    the remainder returned.

    As an example, "set a timer for 5 minutes" would return
    (300, "set a timer for").

    Args:
        text (str): string containing a duration
        resolution (DurationResolution): format to return extracted duration on
        replace_token (str): string to replace consumed words with

    Returns:
        (timedelta, str):
                    A tuple containing the duration and the remaining text
                    not consumed in the parsing. The first value will
                    be None if no duration is found. The text returned
                    will have whitespace stripped from the ends.
    """
    if not text:
        return None

    pattern = r"(?P<value>\d+(?:\.?\d+)?)(?:\s+|\-){unit}s?"
    # text normalization
    original_text = text
    text = _convert_words_to_numbers_en(text)
    text = text.replace("centuries", "century").replace("millenia",
                                                        "millennium")
    text = text.replace("a day", "1 day").replace("a year", "1 year") \
        .replace("a decade", "1 decade").replace("a century", "1 century") \
        .replace("a millennium", "1 millennium")

    # we are always replacing 2 words, {N} {unit}
    _replace_token = (replace_token + " " + replace_token) \
        if replace_token else ""

    if resolution == DurationResolution.TIMEDELTA:
        si_units = {
            'microseconds': None,
            'milliseconds': None,
            'seconds': None,
            'minutes': None,
            'hours': None,
            'days': None,
            'weeks': None
        }

        units = ['months', 'years', 'decades', 'centurys', 'millenniums'] + \
                list(si_units.keys())

        for unit in units:
            unit_pattern = pattern.format(
                unit=unit[:-1])  # remove 's' from unit
            matches = re.findall(unit_pattern, text)
            value = sum(map(float, matches))
            text = re.sub(unit_pattern, _replace_token, text)
            if unit == "days":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += value
            elif unit == "months":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += DAYS_IN_1_MONTH * value
            elif unit == "years":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += DAYS_IN_1_YEAR * value
            elif unit == "decades":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += 10 * DAYS_IN_1_YEAR * value
            elif unit == "centurys":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += 100 * DAYS_IN_1_YEAR * value
            elif unit == "millenniums":
                if si_units["days"] is None:
                    si_units["days"] = 0
                si_units["days"] += 1000 * DAYS_IN_1_YEAR * value
            else:
                si_units[unit] = value
        duration = timedelta(**si_units) if any(si_units.values()) else None
    elif resolution in [DurationResolution.RELATIVEDELTA,
                        DurationResolution.RELATIVEDELTA_APPROXIMATE,
                        DurationResolution.RELATIVEDELTA_FALLBACK,
                        DurationResolution.RELATIVEDELTA_STRICT]:
        relative_units = {
            'microseconds': None,
            'seconds': None,
            'minutes': None,
            'hours': None,
            'days': None,
            'weeks': None,
            'months': None,
            'years': None
        }

        units = ['decades', 'centurys', 'millenniums', 'milliseconds'] + \
                list(relative_units.keys())
        for unit in units:
            unit_pattern = pattern.format(
                unit=unit[:-1])  # remove 's' from unit
            matches = re.findall(unit_pattern, text)
            value = sum(map(float, matches))
            text = re.sub(unit_pattern, _replace_token, text)
            # relativedelta does not support milliseconds
            if unit == "milliseconds":
                if relative_units["microseconds"] is None:
                    relative_units["microseconds"] = 0
                relative_units["microseconds"] += value * 1000
            elif unit == "microseconds":
                if relative_units["microseconds"] is None:
                    relative_units["microseconds"] = 0
                relative_units["microseconds"] += value
            # relativedelta does not support decades, centuries or millennia
            elif unit == "years":
                if relative_units["years"] is None:
                    relative_units["years"] = 0
                relative_units["years"] += value
            elif unit == "decades":
                if relative_units["years"] is None:
                    relative_units["years"] = 0
                relative_units["years"] += value * 10
            elif unit == "centurys":
                if relative_units["years"] is None:
                    relative_units["years"] = 0
                relative_units["years"] += value * 100
            elif unit == "millenniums":
                if relative_units["years"] is None:
                    relative_units["years"] = 0
                relative_units["years"] += value * 1000
            else:
                relative_units[unit] = value

        # microsecond, month, year must be ints
        relative_units["microseconds"] = int(relative_units["microseconds"])
        if resolution == DurationResolution.RELATIVEDELTA_FALLBACK:
            for unit in ["months", "years"]:
                value = relative_units[unit]
                _leftover, _ = math.modf(value)
                if _leftover != 0:
                    print("[WARNING] relativedelta requires {unit} to be an "
                          "integer".format(unit=unit))
                    # fallback to timedelta resolution
                    return extract_duration_en(original_text,
                                               DurationResolution.TIMEDELTA,
                                               replace_token)
                relative_units[unit] = int(value)
        elif resolution == DurationResolution.RELATIVEDELTA_APPROXIMATE:
            _leftover, year = math.modf(relative_units["years"])
            relative_units["months"] += 12 * _leftover
            relative_units["years"] = int(year)
            _leftover, month = math.modf(relative_units["months"])
            relative_units["days"] += DAYS_IN_1_MONTH * _leftover
            relative_units["months"] = int(month)
        else:
            for unit in ["months", "years"]:
                value = relative_units[unit]
                _leftover, _ = math.modf(value)
                if _leftover != 0:
                    raise ValueError("relativedelta requires {unit} to be an "
                                     "integer".format(unit=unit))
                relative_units[unit] = int(value)
        duration = relativedelta(**relative_units) if \
            any(relative_units.values()) else None
    else:
        microseconds = 0
        units = ['months', 'years', 'decades', 'centurys', 'millenniums',
                 "microseconds", "milliseconds", "seconds", "minutes",
                 "hours", "days", "weeks"]

        for unit in units:
            unit_pattern = pattern.format(
                unit=unit[:-1])  # remove 's' from unit
            matches = re.findall(unit_pattern, text)
            value = sum(map(float, matches))
            text = re.sub(unit_pattern, _replace_token, text)
            if unit == "microseconds":
                microseconds += value
            elif unit == "milliseconds":
                microseconds += value * 1000
            elif unit == "seconds":
                microseconds += value * 1000 * 1000
            elif unit == "minutes":
                microseconds += value * 1000 * 1000 * 60
            elif unit == "hours":
                microseconds += value * 1000 * 1000 * 60 * 60
            elif unit == "days":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24
            elif unit == "weeks":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * 7
            elif unit == "months":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * \
                                DAYS_IN_1_MONTH
            elif unit == "years":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * \
                                DAYS_IN_1_YEAR
            elif unit == "decades":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * \
                                DAYS_IN_1_YEAR * 10
            elif unit == "centurys":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * \
                                DAYS_IN_1_YEAR * 100
            elif unit == "millenniums":
                microseconds += value * 1000 * 1000 * 60 * 60 * 24 * \
                                DAYS_IN_1_YEAR * 1000

        if resolution == DurationResolution.TOTAL_MICROSECONDS:
            duration = microseconds
        elif resolution == DurationResolution.TOTAL_MILLISECONDS:
            duration = microseconds / 1000
        elif resolution == DurationResolution.TOTAL_SECONDS:
            duration = microseconds / (1000 * 1000)
        elif resolution == DurationResolution.TOTAL_MINUTES:
            duration = microseconds / (1000 * 1000 * 60)
        elif resolution == DurationResolution.TOTAL_HOURS:
            duration = microseconds / (1000 * 1000 * 60 * 60)
        elif resolution == DurationResolution.TOTAL_DAYS:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24)
        elif resolution == DurationResolution.TOTAL_WEEKS:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 * 7)
        elif resolution == DurationResolution.TOTAL_MONTHS:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 *
                                       DAYS_IN_1_MONTH)
        elif resolution == DurationResolution.TOTAL_YEARS:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 *
                                       DAYS_IN_1_YEAR)
        elif resolution == DurationResolution.TOTAL_DECADES:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 *
                                       DAYS_IN_1_YEAR * 10)
        elif resolution == DurationResolution.TOTAL_CENTURIES:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 *
                                       DAYS_IN_1_YEAR * 100)
        elif resolution == DurationResolution.TOTAL_MILLENNIUMS:
            duration = microseconds / (1000 * 1000 * 60 * 60 * 24 *
                                       DAYS_IN_1_YEAR * 1000)
        else:
            raise ValueError
    if not replace_token:
        text = text.strip()
    return duration, text


def extract_datetime_en(text, anchorDate=None, default_time=None):
    """ Convert a human date reference into an exact datetime

    Convert things like
        "today"
        "tomorrow afternoon"
        "next Tuesday at 4pm"
        "August 3rd"
    into a datetime.  If a reference date is not provided, the current
    local time is used.  Also consumes the words used to define the date
    returning the remaining string.  For example, the string
       "what is Tuesday's weather forecast"
    returns the date for the forthcoming Tuesday relative to the reference
    date and the remainder string
       "what is weather forecast".

    The "next" instance of a day or weekend is considered to be no earlier than
    48 hours in the future. On Friday, "next Monday" would be in 3 days.
    On Saturday, "next Monday" would be in 9 days.

    Args:
        text (str): string containing date words
        anchorDate (datetime): A reference date/time for "tommorrow", etc
        default_time (time): Time to set if no time was found in the string

    Returns:
        [datetime, str]: An array containing the datetime and the remaining
                         text not consumed in the parsing, or None if no
                         date or time related text was found.
    """

    def clean_string(s):
        # normalize and lowercase utt  (replaces words with numbers)
        s = _convert_words_to_numbers_en(s, ordinals=None)
        # clean unneeded punctuation and capitalization among other things.
        s = s.lower().replace('?', '').replace(',', '') \
            .replace(' the ', ' ').replace(' a ', ' ').replace(' an ', ' ') \
            .replace("o' clock", "o'clock").replace("o clock", "o'clock") \
            .replace("o ' clock", "o'clock").replace("o 'clock", "o'clock") \
            .replace("oclock", "o'clock").replace("couple", "2") \
            .replace("centuries", "century").replace("decades", "decade") \
            .replace("millenniums", "millennium")

        wordList = s.split()
        for idx, word in enumerate(wordList):
            word = word.replace("'s", "")

            ordinals = ["rd", "st", "nd", "th"]
            if word[0].isdigit():
                for ordinal in ordinals:
                    # "second" is the only case we should not do this
                    if ordinal in word and "second" not in word:
                        word = word.replace(ordinal, "")
            wordList[idx] = word

        return wordList

    def date_found():
        return found or \
               (
                       datestr != "" or
                       yearOffset != 0 or monthOffset != 0 or
                       dayOffset is True or hrOffset != 0 or
                       hrAbs or minOffset != 0 or
                       minAbs or secOffset != 0
               )

    if not anchorDate:
        anchorDate = now_local()

    if text == "":
        return None
    default_time = default_time or time(0, 0, 0)
    found = False
    daySpecified = False
    dayOffset = False
    monthOffset = 0
    yearOffset = 0
    today = anchorDate.strftime("%w")
    wkday = anchorDate.weekday()  # 0 - monday
    currentYear = anchorDate.strftime("%Y")
    fromFlag = False
    datestr = ""
    hasYear = False
    timeQualifier = ""

    timeQualifiersAM = ['morning']
    timeQualifiersPM = ['afternoon', 'evening', 'night', 'tonight']
    timeQualifiersList = set(timeQualifiersAM + timeQualifiersPM)
    year_markers = ['in', 'on', 'of']
    past_markers = ["last", "past"]
    earlier_markers = ["ago", "earlier"]
    later_markers = ["after", "later"]
    future_markers = ["in", "within"]  # in a month -> + 1 month timedelta
    future_1st_markers = ["next"]  # next month -> day 1 of next month
    markers = year_markers + ['at', 'by', 'this', 'around', 'for', "within"]
    days = ['monday', 'tuesday', 'wednesday',
            'thursday', 'friday', 'saturday', 'sunday']
    months = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november',
              'december']
    recur_markers = days + [d + 's' for d in days] + ['weekend', 'weekday',
                                                      'weekends', 'weekdays']
    monthsShort = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july', 'aug',
                   'sept', 'oct', 'nov', 'dec']
    year_multiples = ["decade", "century", "millennium"]
    day_multiples = ["weeks", "months", "years"]
    past_markers = ["was", "last", "past"]

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == "":
            continue
        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""

        # this isn't in clean string because I don't want to save back to words
        word = word.rstrip('s')
        start = idx
        used = 0
        # save timequalifier for later
        if word in earlier_markers and dayOffset:
            dayOffset = - dayOffset
            used += 1
        elif word == "now" and not datestr:
            resultStr = " ".join(words[idx + 1:])
            resultStr = ' '.join(resultStr.split())
            extractedDate = anchorDate.replace(microsecond=0)
            return [extractedDate, resultStr]
        elif wordNext in year_multiples:
            multiplier = None
            if is_numeric(word):
                try:
                    multiplier = float(word)
                except:
                    multiplier = extract_number_en(word)
            multiplier = multiplier or 1
            _leftover = "0"
            if int(multiplier) != multiplier:
                multiplier, _leftover = str(multiplier).split(".")
            multiplier = int(multiplier)

            used += 2
            if wordNext == "decade":
                yearOffset = multiplier * 10 + int(_leftover[:1])
            elif wordNext == "century":
                yearOffset = multiplier * 100 + int(_leftover[:2]) * 10
            elif wordNext == "millennium":
                yearOffset = multiplier * 1000 + int(_leftover[:3]) * 100

            if wordNextNext in earlier_markers:
                yearOffset = yearOffset * -1
                used += 1
            elif word in past_markers:
                yearOffset = yearOffset * -1
            elif wordPrev in past_markers:
                yearOffset = yearOffset * -1
                start -= 1
                used += 1

        elif word in year_markers and wordNext.isdigit() and len(wordNext) == 4:
            yearOffset = int(wordNext) - int(currentYear)
            used += 2
            hasYear = True
        # couple of
        elif word == "2" and wordNext == "of" and \
                wordNextNext in year_multiples:
            multiplier = 2
            used += 3
            if wordNextNext == "decade":
                yearOffset = multiplier * 10
            elif wordNextNext == "century":
                yearOffset = multiplier * 100
            elif wordNextNext == "millennium":
                yearOffset = multiplier * 1000
        elif word == "2" and wordNext == "of" and \
                wordNextNext in day_multiples:
            multiplier = 2
            used += 3
            if wordNextNext == "years":
                yearOffset = multiplier
            elif wordNextNext == "months":
                monthOffset = multiplier
            elif wordNextNext == "weeks":
                dayOffset = multiplier * 7
        elif word in timeQualifiersList:
            timeQualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == "today" and not fromFlag:
            dayOffset = 0
            used += 1
        elif word == "tomorrow" and not fromFlag:
            dayOffset = 1
            used += 1
        elif word == "day" and wordNext == "before" and wordNextNext == "yesterday" and not fromFlag:
            dayOffset = -2
            used += 3
        elif word == "before" and wordNext == "yesterday" and not fromFlag:
            dayOffset = -2
            used += 2
        elif word == "yesterday" and not fromFlag:
            dayOffset = -1
            used += 1
        elif (word == "day" and
              wordNext == "after" and
              wordNextNext == "tomorrow" and
              not fromFlag and
              (not wordPrev or not wordPrev[0].isdigit())):
            dayOffset = 2
            used = 3
            if wordPrev == "the":
                start -= 1
                used += 1
        # parse 5 days, 10 weeks, last week, next week
        elif word == "day" and wordNext not in earlier_markers:
            if wordPrev and wordPrev[0].isdigit():
                dayOffset += int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev in past_markers:
                    dayOffset = dayOffset * -1
                    start -= 1
                    used += 1

            # next day
            # normalize step makes "in a day" -> "in day"
            elif wordPrev and wordPrev in future_markers + future_1st_markers:
                dayOffset += 1
                start -= 1
                used = 2
            elif wordPrev in past_markers:
                dayOffset = -1
                start -= 1
                used = 2
        # parse X days ago
        elif word == "day" and wordNext in earlier_markers:
            if wordPrev and wordPrev[0].isdigit():
                dayOffset -= int(wordPrev)
                start -= 1
                used = 3
            else:
                dayOffset -= 1
                used = 2
        # parse last/past/next week and in/after X weeks
        elif word == "week" and not fromFlag and wordPrev and wordNext not in earlier_markers:
            if wordPrev[0].isdigit():
                dayOffset += int(wordPrev) * 7
                start -= 1
                used = 2
                if wordPrevPrev in past_markers:
                    dayOffset = dayOffset * -1
                    start -= 1
                    used += 1
            # next week -> next monday
            elif wordPrev in future_1st_markers:
                dayOffset = 7 - wkday
                start -= 1
                used = 2
            # normalize step makes "in a week" -> "in week"
            elif wordPrev in future_markers:
                dayOffset = 7
                start -= 1
                used = 2
            elif wordPrev in past_markers:
                dayOffset = -7
                start -= 1
                used = 2
        # parse X weeks ago
        elif word == "week" and not fromFlag and wordNext in earlier_markers:
            if wordPrev[0].isdigit():
                dayOffset -= int(wordPrev) * 7
                start -= 1
                used = 3
            else:
                dayOffset -= 7
                used = 2
        # parse last/past/next weekend and in/after X weekends
        elif word == "weekend" and not fromFlag and wordPrev and wordNext not in earlier_markers:
            # in/after X weekends
            if wordPrev[0].isdigit():
                n = int(wordPrev)
                dayOffset += 7 - wkday  # next monday -> 1 weekend
                n -= 1
                dayOffset += n * 7
                start -= 1
                used = 2
                if wordPrevPrev in past_markers:
                    dayOffset = dayOffset * -1
                    start -= 1
                    used += 1
            # next weekend -> next saturday
            elif wordPrev in future_1st_markers:
                if wkday < 5:
                    dayOffset = 5 - wkday
                elif wkday == 5:
                    dayOffset = 7
                else:
                    dayOffset = 6
                start -= 1
                used = 2
            # normalize step makes "in a weekend" -> "in weekend" (next monday)
            elif wordPrev in future_markers:
                dayOffset += 7 - wkday  # next monday
                start -= 1
                used = 2
            # last/past weekend -> last/past saturday
            elif wordPrev in past_markers:
                dayOffset -= wkday + 2
                start -= 1
                used = 2
        # parse X weekends ago
        elif word == "weekend" and not fromFlag and wordNext in earlier_markers:
            dayOffset -= wkday + 3  # past friday "one weekend ago"
            used = 2
            # X weekends ago
            if wordPrev and wordPrev[0].isdigit():
                n = int(wordPrev) - 1
                dayOffset -= n * 7
                start -= 1
                used = 3
        # parse 10 months, next month, last month
        elif word == "month" and not fromFlag and wordPrev and wordNext not in earlier_markers:
            if wordPrev[0].isdigit():
                monthOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev in past_markers:
                    monthOffset = monthOffset * -1
                    start -= 1
                    used += 1
            # next month -> day 1
            elif wordPrev in future_1st_markers:
                next_dt = (anchorDate.replace(day=1) + timedelta(days=32)).replace(day=1)
                dayOffset = (next_dt - anchorDate).days
                start -= 1
                used = 2
            # normalize step makes "in a month" -> "in month"
            elif wordPrev in future_markers:
                monthOffset = 1
                start -= 1
                used = 2
            elif wordPrev in past_markers:
                monthOffset = -1
                start -= 1
                used = 2
        elif word == "month" and wordNext in earlier_markers:
            if wordPrev and wordPrev[0].isdigit():
                monthOffset -= int(wordPrev)
                start -= 1
                used = 3
            else:
                monthOffset -= 1
                used = 2
        # parse 5 years, next year, last year
        elif word == "year" and not fromFlag and wordPrev and wordNext not in earlier_markers:
            if wordPrev[0].isdigit():
                yearOffset = int(wordPrev)
                start -= 1
                used = 2
                if wordPrevPrev in past_markers:
                    yearOffset = yearOffset * -1
                    start -= 1
                    used += 1
            # next year -> day 1
            elif wordPrev in future_1st_markers:
                next_dt = anchorDate.replace(day=1, month=1, year=anchorDate.year + 1)
                dayOffset = (next_dt - anchorDate).days
                start -= 1
                used = 2
            # normalize step makes "in a year" -> "in year"
            elif wordPrev in future_markers:
                yearOffset = 1
                start -= 1
                used = 2
            elif wordPrev in past_markers:
                yearOffset = -1
                start -= 1
                used = 2
        elif word == "year" and wordNext in earlier_markers:
            if wordPrev and wordPrev[0].isdigit():
                yearOffset -= int(wordPrev)
                start -= 1
                used = 3
            else:
                yearOffset -= 1
                used = 2

        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not fromFlag:
            d = days.index(word)
            dayOffset = (d + 1) - int(today)
            used = 1
            if dayOffset < 0:
                dayOffset += 7
            if wordPrev == "next":
                if dayOffset <= 2:
                    dayOffset += 7
                used += 1
                start -= 1
            elif wordPrev in past_markers:
                dayOffset -= 7
                used += 1
                start -= 1
        # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in monthsShort and not fromFlag:
            try:
                m = months.index(word)
            except ValueError:
                m = monthsShort.index(word)
            used += 1
            datestr = months[m]
            if wordPrev and (wordPrev[0].isdigit() or
                             (wordPrev == "of" and wordPrevPrev[0].isdigit())):
                if wordPrev == "of" and wordPrevPrev[0].isdigit():
                    datestr += " " + words[idx - 2]
                    used += 1
                    start -= 1
                else:
                    datestr += " " + wordPrev
                start -= 1
                used += 1
                if wordNext and wordNext[0].isdigit():
                    datestr += " " + wordNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False

            elif wordNext and wordNext[0].isdigit():
                datestr += " " + wordNext
                used += 1
                if wordNextNext and wordNextNext[0].isdigit():
                    datestr += " " + wordNextNext
                    used += 1
                    hasYear = True
                else:
                    hasYear = False
            # if no date indicators found, it may not be the month of May
            # may "i/we" ...
            # "... may be"
            elif word == 'may' and wordNext in ['i', 'we', 'be']:
                datestr = ""
            # when was MONTH
            elif not hasYear and wordPrev in past_markers:
                if anchorDate.month > m:
                    datestr += f" {anchorDate.year}"
                else:
                    datestr += f" {anchorDate.year - 1}"
                hasYear = True
            # when is MONTH
            elif not hasYear:
                if anchorDate.month > m:
                    datestr += f" {anchorDate.year + 1}"
                else:
                    datestr += f" {anchorDate.year}"
                hasYear = True
        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + monthsShort
        validFollowups.append("today")
        validFollowups.append("tomorrow")
        validFollowups.append("yesterday")
        validFollowups.append("next")
        validFollowups.append("last")
        validFollowups.append("past")
        validFollowups.append("now")
        validFollowups.append("this")
        if (word == "from" or word == "after") and wordNext in validFollowups:
            used = 2
            fromFlag = True
            if wordNext == "tomorrow":
                dayOffset += 1
            elif wordNext == "yesterday":
                dayOffset -= 1
            elif wordNext in days:
                d = days.index(wordNext)
                tmpOffset = (d + 1) - int(today)
                used = 2
                if tmpOffset < 0:
                    tmpOffset += 7
                dayOffset += tmpOffset
            elif wordNextNext and wordNextNext in days:
                d = days.index(wordNextNext)
                tmpOffset = (d + 1) - int(today)
                used = 3
                if wordNext in future_1st_markers:
                    if dayOffset <= 2:
                        tmpOffset += 7
                    used += 1
                    start -= 1
                elif wordNext in past_markers:
                    tmpOffset -= 7
                    used += 1
                    start -= 1
                dayOffset += tmpOffset
        if used > 0:
            if start - 1 > 0 and words[start - 1] == "this":
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ""

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ""
            found = True
            daySpecified = True

    # parse time
    hrOffset = 0
    minOffset = 0
    secOffset = 0
    hrAbs = None
    minAbs = None
    military = False

    for idx, word in enumerate(words):
        if word == "":
            continue

        wordPrevPrev = words[idx - 2] if idx > 1 else ""
        wordPrev = words[idx - 1] if idx > 0 else ""
        wordNext = words[idx + 1] if idx + 1 < len(words) else ""
        wordNextNext = words[idx + 2] if idx + 2 < len(words) else ""
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == "noon":
            hrAbs = 12
            used += 1
        elif word == "midnight":
            hrAbs = 0
            used += 1
        elif word == "morning":
            if hrAbs is None:
                hrAbs = 8
            used += 1
        elif word == "afternoon":
            if hrAbs is None:
                hrAbs = 15
            used += 1
        elif word == "evening":
            if hrAbs is None:
                hrAbs = 19
            used += 1
        elif word == "tonight" or word == "night":
            if hrAbs is None:
                hrAbs = 22
            # used += 1 ## NOTE this breaks other tests, TODO refactor me!

        # couple of time_unit
        elif word == "2" and wordNext == "of" and \
                wordNextNext in ["hours", "minutes", "seconds"]:
            used += 3
            if wordNextNext == "hours":
                hrOffset = 2
            elif wordNextNext == "minutes":
                minOffset = 2
            elif wordNextNext == "seconds":
                secOffset = 2
        # parse in a/next second/minute/hour
        elif wordNext == "hour" and word in future_markers + future_1st_markers:
            used += 2
            hrOffset = 1
        elif wordNext == "minute" and word in future_markers + future_1st_markers:
            used += 2
            minOffset = 1
        elif wordNext == "second" and word in future_markers + future_1st_markers:
            used += 2
            secOffset = 1
        # parse last/past  second/minute/hour
        elif wordNext == "hour" and word in past_markers:
            used += 2
            hrOffset = - 1
        elif wordNext == "minute" and word in past_markers:
            used += 2
            minOffset = - 1
        elif wordNext == "second" and word in past_markers:
            used += 2
            secOffset = - 1
        # parse half an hour, quarter hour
        elif word == "hour" and \
                (wordPrev in markers or wordPrevPrev in markers):
            if wordPrev == "half":
                minOffset = 30
            elif wordPrev == "quarter":
                minOffset = 15
            elif wordPrevPrev == "quarter":
                minOffset = 15
                if idx > 2 and words[idx - 3] in markers:
                    words[idx - 3] = ""
                words[idx - 2] = ""
            elif wordPrev == "within":
                hrOffset = 1
            else:
                hrOffset = 1
            if wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "this":
                    daySpecified = True
            words[idx - 1] = ""
            used += 1
            hrAbs = -1
            minAbs = -1
        # parse 5:00 am, 12:00 p.m., etc
        elif word[0].isdigit():
            isTime = True
            strHH = ""
            strMM = ""
            remainder = ""
            wordNextNextNext = words[idx + 3] \
                if idx + 3 < len(words) else ""
            if wordNext == "tonight" or wordNextNext == "tonight" or \
                    wordPrev == "tonight" or wordPrevPrev == "tonight" or \
                    wordNextNextNext == "tonight":
                remainder = "pm"
                used += 1
                if wordPrev == "tonight":
                    words[idx - 1] = ""
                if wordPrevPrev == "tonight":
                    words[idx - 2] = ""
                if wordNextNext == "tonight":
                    used += 1
                if wordNextNextNext == "tonight":
                    used += 1

            if ':' in word:
                # parse colons
                # "3:00 in the morning"
                stage = 0
                length = len(word)
                for i in range(length):
                    if stage == 0:
                        if word[i].isdigit():
                            strHH += word[i]
                        elif word[i] == ":":
                            stage = 1
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 1:
                        if word[i].isdigit():
                            strMM += word[i]
                        else:
                            stage = 2
                            i -= 1
                    elif stage == 2:
                        remainder = word[i:].replace(".", "")
                        break
                if remainder == "":
                    nextWord = wordNext.replace(".", "")
                    if nextWord == "am" or nextWord == "pm":
                        remainder = nextWord
                        used += 1

                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "morning":
                        remainder = "am"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "afternoon":
                        remainder = "pm"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "the" and \
                            words[idx + 3] == "evening":
                        remainder = "pm"
                        used += 3
                    elif wordNext == "in" and wordNextNext == "morning":
                        remainder = "am"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "afternoon":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "in" and wordNextNext == "evening":
                        remainder = "pm"
                        used += 2
                    elif wordNext == "this" and wordNextNext == "morning":
                        remainder = "am"
                        used = 2
                        daySpecified = True
                    elif wordNext == "this" and wordNextNext == "afternoon":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "this" and wordNextNext == "evening":
                        remainder = "pm"
                        used = 2
                        daySpecified = True
                    elif wordNext == "at" and wordNextNext == "night":
                        if strHH and int(strHH) > 5:
                            remainder = "pm"
                        else:
                            remainder = "am"
                        used += 2

                    else:
                        if timeQualifier != "":
                            military = True
                            if strHH and int(strHH) <= 12 and \
                                    (timeQualifier in timeQualifiersPM):
                                strHH += str(int(strHH) + 12)

            else:
                # try to parse numbers without colons
                # 5 hours, 10 minutes etc.
                length = len(word)
                strNum = ""
                remainder = ""
                for i in range(length):
                    if word[i].isdigit():
                        strNum += word[i]
                    else:
                        remainder += word[i]

                if remainder == "":
                    remainder = wordNext.replace(".", "").lstrip().rstrip()
                if (
                        remainder == "pm" or
                        wordNext == "pm" or
                        remainder == "p.m." or
                        wordNext == "p.m."):
                    strHH = strNum
                    remainder = "pm"
                    used = 1
                elif (
                        remainder == "am" or
                        wordNext == "am" or
                        remainder == "a.m." or
                        wordNext == "a.m."):
                    strHH = strNum
                    remainder = "am"
                    used = 1
                elif (
                        remainder in recur_markers or
                        wordNext in recur_markers or
                        wordNextNext in recur_markers):
                    # Ex: "7 on mondays" or "3 this friday"
                    # Set strHH so that isTime == True
                    # when am or pm is not specified
                    strHH = strNum
                    used = 1
                else:
                    if (
                            int(strNum) > 100 and
                            (
                                    wordPrev == "o" or
                                    wordPrev == "oh"
                            )):
                        # 0800 hours (pronounced oh-eight-hundred)
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "hours":
                            used += 1
                    elif (
                            (wordNext == "hours" or wordNext == "hour" or
                             remainder == "hours" or remainder == "hour") and
                            word[0] != '0' and
                            (int(strNum) < 100 or int(strNum) > 2400 or wordPrev in past_markers)):
                        # ignores military time
                        # "in 3 hours"
                        hrOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                        # in last N hours
                        if wordPrev in past_markers:
                            start -= 1
                            used += 1
                            hrOffset = hrOffset * -1

                    elif wordNext == "minutes" or wordNext == "minute" or \
                            remainder == "minutes" or remainder == "minute":
                        # "in 10 minutes"
                        minOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                        # in last N minutes
                        if wordPrev in past_markers:
                            start -= 1
                            used += 1
                            minOffset = minOffset * -1
                    elif wordNext == "seconds" or wordNext == "second" \
                            or remainder == "seconds" or remainder == "second":
                        # in 5 seconds
                        secOffset = int(strNum)
                        used = 2
                        isTime = False
                        hrAbs = -1
                        minAbs = -1
                        # in last N seconds
                        if wordPrev in past_markers:
                            start -= 1
                            used += 1
                            secOffset = secOffset * -1
                    elif int(strNum) > 100:
                        # military time, eg. "3300 hours"
                        strHH = str(int(strNum) // 100)
                        strMM = str(int(strNum) % 100)
                        military = True
                        if wordNext == "hours" or wordNext == "hour" or \
                                remainder == "hours" or remainder == "hour":
                            used += 1
                    elif wordNext and wordNext[0].isdigit():
                        # military time, e.g. "04 38 hours"
                        strHH = strNum
                        strMM = wordNext
                        military = True
                        used += 1
                        if (wordNextNext == "hours" or
                                wordNextNext == "hour" or
                                remainder == "hours" or remainder == "hour"):
                            used += 1
                    elif (wordNext == ""
                          or wordNext == "o'clock"
                          or (wordNext == "in" and (wordNextNext == "the" or wordNextNext == timeQualifier))
                          or wordNext == 'tonight'
                          or wordNextNext == 'tonight'):
                        strHH = strNum
                        strMM = "00"
                        if wordNext == "o'clock":
                            used += 1

                        if wordNext == "in" or wordNextNext == "in":
                            used += (1 if wordNext == "in" else 2)
                            wordNextNextNext = words[idx + 3] \
                                if idx + 3 < len(words) else ""

                            if (wordNextNext and
                                    (wordNextNext in timeQualifier or
                                     wordNextNextNext in timeQualifier)):
                                if (wordNextNext in timeQualifiersPM or
                                        wordNextNextNext in timeQualifiersPM):
                                    remainder = "pm"
                                    used += 1
                                if (wordNextNext in timeQualifiersAM or
                                        wordNextNextNext in timeQualifiersAM):
                                    remainder = "am"
                                    used += 1

                        if timeQualifier != "":
                            if timeQualifier in timeQualifiersPM:
                                remainder = "pm"
                                used += 1

                            elif timeQualifier in timeQualifiersAM:
                                remainder = "am"
                                used += 1
                            else:
                                # TODO: Unsure if this is 100% accurate
                                used += 1
                                military = True
                    else:
                        isTime = False

            HH = int(strHH) if strHH else 0
            MM = int(strMM) if strMM else 0
            HH = HH + 12 if remainder == "pm" and HH < 12 else HH
            HH = HH - 12 if remainder == "am" and HH >= 12 else HH

            if (not military and
                    remainder not in ['am', 'pm', 'hours', 'minutes',
                                      "second", "seconds",
                                      "hour", "minute"] and
                    ((not daySpecified) or 0 <= dayOffset < 1)):

                # ambiguous time, detect whether they mean this evening or
                # the next morning based on whether it has already passed
                if anchorDate.hour < HH or (anchorDate.hour == HH and
                                            anchorDate.minute < MM):
                    pass  # No modification needed
                elif anchorDate.hour < HH + 12:
                    HH += 12
                else:
                    # has passed, assume the next morning
                    dayOffset += 1

            if timeQualifier in timeQualifiersPM and HH < 12:
                HH += 12

            if HH > 24 or MM > 59:
                isTime = False
                used = 0
            if isTime:
                hrAbs = HH
                minAbs = MM
                used += 1

        if used > 0:
            # removed parsed words from the sentence
            for i in range(used):
                if idx + i >= len(words):
                    break
                words[idx + i] = ""

            if wordPrev == "o" or wordPrev == "oh":
                words[words.index(wordPrev)] = ""

            if wordPrev == "early":
                hrOffset = -1
                words[idx - 1] = ""
                idx -= 1
            elif wordPrev == "late":
                hrOffset = 1
                words[idx - 1] = ""
                idx -= 1
            if idx > 0 and wordPrev in markers:
                words[idx - 1] = ""
                if wordPrev == "this":
                    daySpecified = True
            if idx > 1 and wordPrevPrev in markers:
                words[idx - 2] = ""
                if wordPrevPrev == "this":
                    daySpecified = True

            idx += used - 1
            found = True

    # check that we found a date
    if not date_found():
        return None

    if dayOffset is False:
        dayOffset = 0

    # perform date manipulation

    extractedDate = anchorDate.replace(microsecond=0)

    if datestr != "":
        # date included an explicit date, e.g. "june 5" or "june 2, 2017"
        try:
            temp = datetime.strptime(datestr, "%B %d")
        except ValueError:
            # Try again, allowing the year
            try:
                temp = datetime.strptime(datestr, "%B %d %Y")
            except ValueError:
                # Try again, without day
                try:
                    temp = datetime.strptime(datestr, "%B %Y")
                except ValueError:
                    # Try again, with only month
                    temp = datetime.strptime(datestr, "%B")
        extractedDate = extractedDate.replace(hour=0, minute=0, second=0)
        if not hasYear:
            temp = temp.replace(year=extractedDate.year,
                                tzinfo=extractedDate.tzinfo)
            if extractedDate < temp:
                extractedDate = extractedDate.replace(
                    year=int(currentYear),
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extractedDate.tzinfo)
            else:
                extractedDate = extractedDate.replace(
                    year=int(currentYear) + 1,
                    month=int(temp.strftime("%m")),
                    day=int(temp.strftime("%d")),
                    tzinfo=extractedDate.tzinfo)
        else:
            extractedDate = extractedDate.replace(
                year=int(temp.strftime("%Y")),
                month=int(temp.strftime("%m")),
                day=int(temp.strftime("%d")),
                tzinfo=extractedDate.tzinfo)
    else:
        # ignore the current HH:MM:SS if relative using days or greater
        if hrOffset == 0 and minOffset == 0 and secOffset == 0:
            extractedDate = extractedDate.replace(hour=default_time.hour,
                                                  minute=default_time.minute,
                                                  second=default_time.second)

    if yearOffset != 0:
        extractedDate = extractedDate + relativedelta(years=yearOffset)
    if monthOffset != 0:
        extractedDate = extractedDate + relativedelta(months=monthOffset)
    if dayOffset != 0:
        extractedDate = extractedDate + relativedelta(days=dayOffset)
    if hrOffset != 0:
        extractedDate = extractedDate + relativedelta(hours=hrOffset)
    if minOffset != 0:
        extractedDate = extractedDate + relativedelta(minutes=minOffset)
    if secOffset != 0:
        extractedDate = extractedDate + relativedelta(seconds=secOffset)


    if hrAbs != -1 and minAbs != -1 and not hrOffset and not minOffset and not secOffset:
        # If no time was supplied in the string set the time to default
        # time if it's available
        if hrAbs is None and minAbs is None and default_time is not None:
            hrAbs, minAbs = default_time.hour, default_time.minute
        else:
            hrAbs = hrAbs or 0
            minAbs = minAbs or 0

        extractedDate = extractedDate.replace(hour=hrAbs,
                                              minute=minAbs)

        if (hrAbs != 0 or minAbs != 0) and datestr == "":
            if not daySpecified and anchorDate > extractedDate:
                extractedDate = extractedDate + relativedelta(days=1)

    for idx, word in enumerate(words):
        if words[idx] == "and" and \
                words[idx - 1] == "" and words[idx + 1] == "":
            words[idx] = ""

    resultStr = " ".join(words)
    resultStr = ' '.join(resultStr.split())
    return [extractedDate, resultStr]


def is_fractional_en(input_str, short_scale=True, spoken=True):
    """
    This function takes the given text and checks if it is a fraction.

    Args:
        input_str (str): the string to check if fractional
        short_scale (bool): use short scale if True, long scale if False
        spoken (bool): consider "half", "quarter", "whole" a fraction
    Returns:
        (bool) or (float): False if not a fraction, otherwise the fraction

    """
    if input_str.endswith('s', -1):
        input_str = input_str[:len(input_str) - 1]  # e.g. "fifths"

    fracts = {"whole": 1, "half": 2, "halve": 2, "quarter": 4}
    if short_scale:
        for num in _SHORT_ORDINAL_EN:
            if num > 2:
                fracts[_SHORT_ORDINAL_EN[num]] = num
    else:
        for num in _LONG_ORDINAL_EN:
            if num > 2:
                fracts[_LONG_ORDINAL_EN[num]] = num

    if input_str.lower() in fracts and spoken:
        return 1.0 / fracts[input_str.lower()]
    return False


def extract_numbers_en(text, short_scale=True, ordinals=False):
    """
        Takes in a string and extracts a list of numbers.

    Args:
        text (str): the string to extract a number from
        short_scale (bool): Use "short scale" or "long scale" for large
            numbers -- over a million.  The default is short scale, which
            is now common in most English speaking countries.
            See https://en.wikipedia.org/wiki/Names_of_large_numbers
        ordinals (bool): consider ordinal numbers, e.g. third=3 instead of 1/3
    Returns:
        list: list of extracted numbers as floats
    """
    results = _extract_numbers_with_text_en(tokenize(text),
                                            short_scale, ordinals)
    return [float(result.value) for result in results]


class EnglishNormalizer(Normalizer):
    with open(resolve_resource_file("text/en-us/normalize.json")) as f:
        _default_config = json.load(f)

    def numbers_to_digits(self, utterance):
        return _convert_words_to_numbers_en(utterance, ordinals=None)


def normalize_en(text, remove_articles=True):
    """ English string normalization """
    return EnglishNormalizer().normalize(text, remove_articles)


def get_named_dates_en(location_code=None, year=None):
    year = year or now_local().year
    location_code = location_code or get_active_location_code()
    holidays = {}

    # "universal" holidays
    holidays["christmas"] = date(day=25, month=12, year=year)
    holidays["christmas eve"] = date(day=24, month=12, year=year)
    holidays["new year's eve"] = date(day=31, month=12, year=year)
    holidays["new year"] = date(day=1, month=1, year=year + 1)
    holidays["valentine's day"] = date(day=14, month=2, year=year)

    # Location aware holidays
    country_holidays = CountryHoliday(location_code, years=year)
    for dt, name in country_holidays.items():
        holidays[name] = dt

    # normalization
    for name in list(holidays.keys()):
        dt = holidays[name]
        name = name.lower().strip().replace(" ", "_").replace("'s", "")
        holidays[name] = dt
    return holidays


def get_named_eras_en(location_code=None):
    # NOTE an era is simply a reference date
    # days are counted forwards from this date
    eras = _NAMED_ERAS_EN

    location_code = location_code or get_active_location_code()
    # location dependent eras

    # normalization
    for name in list(eras.keys()):
        dt = eras[name]
        name = name.lower().strip().replace(" ", "_").replace("'s", "")
        eras[name] = dt
    return eras


def get_negative_named_eras_en(location_code=None):
    # NOTE an era is simply a reference date
    # negative era means we count backwards from this date
    eras = {
        "before present": date(day=1, month=1, year=1950)
    }

    location_code = location_code or get_active_location_code()
    # location dependent eras

    # normalization
    for name in list(eras.keys()):
        dt = eras[name]
        name = name.lower().strip().replace(" ", "_").replace("'s", "")
        eras[name] = dt
    return eras


def _date_tokenize_en(date_string, holidays=None):
    date_string = _convert_words_to_numbers_en(date_string, ordinals=True)
    # normalize units
    date_string = date_string \
        .replace("a day", "1 day").replace("a month", "1 month") \
        .replace("a week", "1 week").replace("a year", "1 year") \
        .replace("a century", "1 century").replace("a decade", "1 decade")

    words = date_string.split()
    cleaned = ""
    for idx, word in enumerate(words):
        if word == "-":
            word = "minus"
            words[idx] = word
        elif word == "+":
            word = "plus"
            words[idx] = word
        elif word[0] == "-" and word[1].isdigit():
            cleaned += " minus " + word[1:].rstrip(",.!?;:-)/]=}")
        elif word[0] == "+" and word[1].isdigit():
            cleaned += " plus " + word[1:].rstrip(",.!?;:-)/]=}")
        else:
            cleaned += " " + word.rstrip(",.!?;:-)/]=}") \
                .lstrip(",.!?;:-(/[={")
    for n, ordinal in _ORDINAL_BASE_EN.items():
        cleaned = cleaned.replace(ordinal, str(n))
    cleaned = normalize_en(cleaned, remove_articles=False)

    # normalize holidays into a single word
    holidays = holidays or get_named_dates_en()
    for name, dt in holidays.items():
        name = name.replace("_", " ")
        _standard = name.lower().strip().replace(" ", "_") \
            .replace("'s", "")
        cleaned = cleaned.replace(name, _standard)

    # normalize eras into a single word
    eras = get_named_eras_en()
    for name, dt in eras.items():
        name = name.replace("_", " ")
        _standard = name.lower().strip().replace(" ", "_") \
            .replace("'s", "")
        cleaned = cleaned.replace(name, _standard)

    eras = get_negative_named_eras_en()
    for name, dt in eras.items():
        name = name.replace("_", " ")
        _standard = name.lower().strip().replace(" ", "_") \
            .replace("'s", "")
        cleaned = cleaned.replace(name, _standard)

    return cleaned.split()


def extract_date_en(date_str, ref_date,
                    resolution=DateTimeResolution.DAY,
                    hemisphere=None,
                    location_code=None,
                    greedy=False):
    """

    :param date_str:
    :param ref_date:
    :param resolution:
    :param hemisphere:
    :param greedy: (bool) parse single number as years
    :return:
    """
    if hemisphere is None:
        hemisphere = get_active_hemisphere()
    named_dates = get_named_dates_en(location_code, ref_date.year)
    eras = get_named_eras_en(location_code)
    negative_eras = get_negative_named_eras_en(location_code)

    past_qualifiers = ["ago"]
    relative_qualifiers = ["from", "after", "since"]
    relative_past_qualifiers = ["before"]
    of_qualifiers = ["of"]  # {Nth} day/week/month.... of month/year/century..
    set_qualifiers = ["is", "was"]  # "the year is 2021"

    more_markers = ["plus", "add", "+"]
    less_markers = ["minus", "subtract", "-"]
    past_markers = ["past", "last"]
    future_markers = ["next", "upcoming"]
    most_recent_qualifiers = ["last"]
    location_markers = ["in", "on", "at", "for"]

    now = ["now"]
    today = ["today"]
    this = ["this", "current", "present", "the"]
    mid = ["mid", "middle"]
    tomorrow = ["tomorrow"]
    yesterday = ["yesterday"]
    day_literal = ["day", "days"]
    week_literal = ["week", "weeks"]
    weekend_literal = ["weekend", "weekends"]
    month_literal = ["month", "months"]
    year_literal = ["year", "years"]
    century_literal = ["century", "centuries"]
    decade_literal = ["decade", "decades"]
    millennium_literal = ["millennium", "millenia", "millenniums"]
    hemisphere_literal = ["hemisphere"]
    season_literal = ["season"]
    easter_literal = ["easter"]

    date_words = _date_tokenize_en(date_str, named_dates)
    remainder_words = list(date_words)  # copy to track consumed words

    # check for word boundaries and parse reference dates
    index = 0
    is_relative = False
    is_relative_past = False
    is_past = False
    is_sum = False
    is_subtract = False
    is_of = False
    is_negative_era = False
    delta = None
    date_found = False

    # is this a negative timespan?
    for marker in past_qualifiers:
        if marker in date_words:
            is_past = True
            index = date_words.index(marker)

    # is this relative to (after) a date?
    for marker in relative_qualifiers:
        if marker in date_words:
            is_relative = True
            index = date_words.index(marker)

    # is this relative to (before) a date?
    for marker in relative_past_qualifiers:
        if marker in date_words:
            is_relative_past = True
            index = date_words.index(marker)

    # is this a timespan in the future?
    for marker in more_markers:
        if marker in date_words:
            is_sum = True
            index = date_words.index(marker)

    # is this a timespan in the past?
    for marker in less_markers:
        if marker in date_words:
            is_subtract = True
            index = date_words.index(marker)

    # cardinal of thing
    # 3rd day of the 4th month of 1994
    for marker in of_qualifiers:
        if marker in date_words:
            is_of = True
            index = date_words.index(marker)

    # parse negative eras, "5467 before present"
    for era in negative_eras:
        if era in date_words:
            is_negative_era = True
            index = date_words.index(era)

    # parse {date} of {negative_era}
    if is_negative_era:
        _anchor_date = negative_eras[date_words[index]]
        _extracted_date = None
        duration_str = " ".join(date_words[:index])

        # equivalent to {negative_era} - {duration}
        if duration_str:

            # parse {date} {negative_era}
            extracted_date, _r = extract_date_en(
                duration_str, _anchor_date,
                resolution=DateTimeResolution.BEFORE_PRESENT)
            # TODO save era resolution in dict, this is hardcoded for
            #  testing only

            if not extracted_date:
                # parse {duration} {negative_era}
                delta, _r = extract_duration_en(
                    duration_str, replace_token='_',
                    resolution=DurationResolution.RELATIVEDELTA_FALLBACK)

                if not delta:
                    _year = date_words[index - 1]
                    # parse {YEAR} {negative_era}
                    if is_numeric(_year):
                        delta = relativedelta(years=int(_year))
                    else:
                        raise RuntimeError(
                            "Could not extract duration from: " + duration_str)

                # subtract duration
                extracted_date = _anchor_date - delta

                # update consumed words
                remainder_words[index] = "_"
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[idx] = "_"
        else:
            extracted_date = _anchor_date
        date_found = True
        # update consumed words
        remainder_words[index] = "_"

    # parse {X} of {reference_date}
    if is_of:
        remainder_words[index] = ""
        _date_words = date_words[index + 1:]

        # parse {ORDINAL} day/week/month/year... of {reference_date}
        _ordinal_words = date_words[:index]  # 3rd day / 4th week of the year
        _number = None

        _unit = "day"  # TODO is this a sane default ?
        _res = DateTimeResolution.DAY_OF_MONTH

        # parse "{NUMBER} {day/week/month/year...} "
        if len(_ordinal_words) > 1:
            _ordinal = _ordinal_words[-2]
            _unit = _ordinal_words[-1]

            remainder_words[index - 1] = ""

            if is_numeric(_ordinal):
                _number = int(_ordinal)
                remainder_words[index - 2] = ""
            # parse "last {day/week/month/year...} "
            elif _ordinal_words[0] in most_recent_qualifiers:
                _number = -1
                remainder_words[index - len(_ordinal_words)] = ""

        # parse "{NUMBER}"
        elif len(_ordinal_words) == 1:
            _ordinal = _ordinal_words[0]
            if is_numeric(_ordinal):
                _number = int(_ordinal)
                remainder_words[index - 1] = ""

        # parse resolution {X} {day/week/month/year...} of {Y}
        if _number:
            _best_idx = len(_date_words) - 1

            # parse "Nth {day/week/month/year...} of {YEAR}"
            if len(_date_words) and is_numeric(_date_words[0]):
                _res = DateTimeResolution.DAY_OF_YEAR

            # parse "{NUMBER} day
            if _unit in day_literal:
                # parse "{NUMBER} day of month
                for marker in month_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DAY_OF_MONTH
                # parse "{NUMBER} day of year
                for marker in year_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DAY_OF_YEAR
                # parse "{NUMBER} day of decade
                for marker in decade_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DAY_OF_DECADE
                # parse "{NUMBER} day of century
                for marker in century_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DAY_OF_CENTURY
                # parse "{NUMBER} day of millennium
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DAY_OF_MILLENNIUM

            # parse "{NUMBER} week
            if _unit in week_literal:
                _res = DateTimeResolution.WEEK_OF_MONTH
                # parse "{NUMBER} week of Nth month
                for marker in month_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.WEEK_OF_MONTH
                # parse "{NUMBER} week of Nth year
                for marker in year_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.WEEK_OF_YEAR
                # parse "{NUMBER} week of Nth decade
                for marker in decade_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.WEEK_OF_DECADE
                # parse "{NUMBER} week of Nth century
                for marker in century_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.WEEK_OF_CENTURY
                # parse "{NUMBER} week of Nth millennium
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.WEEK_OF_MILLENNIUM

            # parse "{NUMBER} month
            if _unit in month_literal:
                # parse "{NUMBER} month of Nth year
                _res = DateTimeResolution.MONTH_OF_YEAR
                for marker in year_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.MONTH_OF_YEAR
                # parse "{NUMBER} month of Nth decade
                for marker in decade_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.MONTH_OF_DECADE
                # parse "{NUMBER} month of Nth century
                for marker in century_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        _res = DateTimeResolution.MONTH_OF_CENTURY
                # parse "{NUMBER} month of Nth millenium
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.MONTH_OF_MILLENNIUM

            # parse "{NUMBER} year
            if _unit in year_literal:
                _res = DateTimeResolution.YEAR
                for marker in year_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.YEAR
                for marker in decade_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.YEAR_OF_DECADE
                for marker in century_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.YEAR_OF_CENTURY
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.YEAR_OF_MILLENNIUM

            # parse "{NUMBER} decade
            if _unit in decade_literal:
                _res = DateTimeResolution.DECADE
                for marker in century_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DECADE_OF_CENTURY
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.DECADE_OF_MILLENNIUM

            # parse "{NUMBER} century
            if _unit in century_literal:
                _res = DateTimeResolution.CENTURY
                for marker in millennium_literal:
                    if marker in _date_words:
                        _idx = _date_words.index(marker)
                        if _idx <= _best_idx:
                            _best_idx = _idx
                            _res = DateTimeResolution.CENTURY_OF_MILLENNIUM

            # parse "{NUMBER} millennium
            if _unit in millennium_literal:
                _res = DateTimeResolution.MILLENNIUM

            remainder_words[index + _best_idx] = ""

        # parse {reference_date}
        _date_str = " ".join(_date_words)
        _anchor_date, _r = extract_date_en(_date_str, ref_date, resolution,
                                           hemisphere, greedy=True)

        # update consumed words
        for idx, w in enumerate(_r.split()):
            if w == "_":
                remainder_words[index + 1 + idx] = "_"

        # Parse {Nth} day/week/month/year... of {reference_date}
        if _number and _anchor_date:
            date_found = True
            extracted_date = get_date_ordinal(_number, _anchor_date, _res)
            remainder_words[index] = ""

        # Parse {partial_date} of {partial_reference_date}
        # "summer of 1969"
        elif _anchor_date:
            # TODO should we allow invalid combinations?
            # "summer of january"
            # "12 may of october"
            # "1980 of 2002"

            _partial_date_str = " ".join(_ordinal_words)
            _partial_date, _r = extract_date_en(_partial_date_str,
                                                _anchor_date,
                                                resolution, hemisphere)

            if _partial_date:
                date_found = True
                extracted_date = _partial_date
                remainder_words[index] = ""

                # update consumed words
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[idx] = "_"

    # parse {duration} ago
    if is_past:
        # parse {duration} ago
        duration_str = " ".join(date_words[:index])
        delta, _r = extract_duration_en(duration_str, replace_token='_',
                                        resolution=DurationResolution.RELATIVEDELTA_FALLBACK)
        if not delta:
            raise RuntimeError(
                "Could not extract duration from: " + duration_str)
        remainder_words[index] = ""
        # update consumed words
        for idx, w in enumerate(_r.split()):
            if w == "_":
                remainder_words[idx] = "_"

    # parse {duration} after {date}
    if is_relative:
        # parse {duration} from {reference_date}
        # 1 hour 3 minutes from now
        # 5 days from now
        # 3 weeks after tomorrow
        remainder_words[index] = ""

        duration_str = " ".join(date_words[:index])
        if duration_str:
            delta, _r = extract_duration_en(duration_str, replace_token='_',
                                            resolution=DurationResolution.RELATIVEDELTA_FALLBACK)

            # update consumed words
            for idx, w in enumerate(_r.split()):
                if w == "_":
                    remainder_words[idx] = "_"

            _date_str = " ".join(date_words[index + 1:])
            _anchor_date, _r = extract_date_en(_date_str, ref_date,
                                               hemisphere=hemisphere)
            if not _anchor_date and len(date_words) > index + 1:
                _year = date_words[index + 1]
                if len(_year) == 4 and is_numeric(_year):
                    _anchor_date = date(day=1, month=1, year=int(_year))
                    remainder_words[index + 1] = ""
            else:
                # update consumed words
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[index + 1 + idx] = "_"

            date_found = True
            extracted_date = (_anchor_date or ref_date) + delta

        else:
            _date_str = " ".join(date_words[index + 1:])
            _anchor_date, _r = extract_date_en(_date_str, ref_date,
                                               hemisphere=hemisphere)
            if not _anchor_date:
                _year = date_words[index + 1]
                if len(_year) == 4 and is_numeric(_year):
                    _anchor_date = date(day=1, month=1, year=int(_year))
                    remainder_words[index + 1] = ""
            else:
                # update consumed words
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[index + 1 + idx] = "_"

            ref_date = _anchor_date or ref_date

            # next day
            if resolution == DateTimeResolution.DAY:
                date_found = True
                extracted_date = ref_date + timedelta(days=1)
            # next week
            elif resolution == DateTimeResolution.WEEK:
                delta = timedelta(weeks=1)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_week_range(_anchor_date)
                date_found = True
            # next month
            elif resolution == DateTimeResolution.MONTH:
                delta = timedelta(days=31)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_month_range(_anchor_date)
                date_found = True
            # next year
            elif resolution == DateTimeResolution.YEAR:
                delta = timedelta(days=31 * 12)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_year_range(_anchor_date)
                date_found = True
            # next decade
            elif resolution == DateTimeResolution.DECADE:
                delta = timedelta(days=DAYS_IN_1_YEAR * 10)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_decade_range(_anchor_date)
                date_found = True
            # next century
            elif resolution == DateTimeResolution.CENTURY:
                delta = timedelta(days=DAYS_IN_1_YEAR * 100)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_century_range(_anchor_date)
                date_found = True
            # next millennium
            elif resolution == DateTimeResolution.MILLENNIUM:
                delta = timedelta(days=DAYS_IN_1_YEAR * 1000)
                _anchor_date = ref_date + delta
                extracted_date, _end = get_millennium_range(_anchor_date)
                date_found = True
            else:
                raise ValueError("Invalid Resolution")

    # parse {duration} before {date}
    if is_relative_past:
        # parse {duration} before {reference_date}
        # 3 weeks before tomorrow
        # 5 days before today/tomorrow/tuesday
        remainder_words[index] = ""
        duration_str = " ".join(date_words[:index])
        if duration_str:
            delta, _r = extract_duration_en(duration_str, replace_token='_',
                                            resolution=DurationResolution.RELATIVEDELTA_FALLBACK)

            # update consumed words
            for idx, w in enumerate(_r.split()):
                if w == "_":
                    remainder_words[idx] = "_"

            _date_str = " ".join(date_words[index + 1:])
            _anchor_date, _r = extract_date_en(_date_str, ref_date)
            if not _anchor_date and len(date_words) > index + 1:
                _year = date_words[index + 1]
                if len(_year) == 4 and is_numeric(_year):
                    _anchor_date = date(day=1, month=1, year=int(_year))
                    remainder_words[index + 1] = ""
            else:
                # update consumed words
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[index + 1 + idx] = "_"
            date_found = True
            extracted_date = (_anchor_date or ref_date) - delta
        else:
            _date_str = " ".join(date_words[index + 1:])
            _anchor_date, _r = extract_date_en(_date_str, ref_date)
            if not _anchor_date and len(date_words) > index + 1:
                _year = date_words[index + 1]
                if len(_year) == 4 and is_numeric(_year):
                    _anchor_date = date(day=1, month=1, year=int(_year))
                    remainder_words[index + 1] = ""
            else:
                # update consumed words
                for idx, w in enumerate(_r.split()):
                    if w == "_":
                        remainder_words[index + 1 + idx] = "_"

            ref_date = _anchor_date or ref_date
            # previous day
            if resolution == DateTimeResolution.DAY:
                date_found = True
                extracted_date = ref_date - timedelta(days=1)
            # previous week
            elif resolution == DateTimeResolution.WEEK:
                _anchor_date = ref_date - timedelta(weeks=1)
                extracted_date, _end = get_week_range(_anchor_date)
                date_found = True
            # previous month
            elif resolution == DateTimeResolution.MONTH:
                delta = timedelta(days=DAYS_IN_1_MONTH)
                _anchor_date = ref_date - delta
                extracted_date, _end = get_month_range(_anchor_date)
                date_found = True
            # previous year
            elif resolution == DateTimeResolution.YEAR:
                delta = timedelta(days=DAYS_IN_1_YEAR)
                _anchor_date = ref_date - delta
                extracted_date, _end = get_year_range(_anchor_date)
                date_found = True
            # previous decade
            elif resolution == DateTimeResolution.DECADE:
                delta = timedelta(days=DAYS_IN_1_YEAR * 10)
                _anchor_date = ref_date - delta
                extracted_date, _end = get_decade_range(ref_date)
                date_found = True
            # previous century
            elif resolution == DateTimeResolution.CENTURY:
                delta = timedelta(days=DAYS_IN_1_YEAR * 100)
                _anchor_date = ref_date - delta
                extracted_date, _end = get_century_range(ref_date)
                date_found = True
            # previous millennium
            elif resolution == DateTimeResolution.MILLENNIUM:
                delta = timedelta(days=DAYS_IN_1_YEAR * 1000)
                _anchor_date = ref_date - delta
                extracted_date, _end = get_century_range(ref_date)
                date_found = True
            else:
                raise ValueError("Invalid Sensitivity")

    # parse {date} plus/minus {duration}
    if is_sum or is_subtract:
        # parse {reference_date} plus {duration}
        # january 5 plus 2 weeks
        # parse {reference_date} minus {duration}
        # now minus 10 days
        duration_str = " ".join(date_words[index + 1:])
        delta, _r = extract_duration_en(duration_str, replace_token='_',
                                        resolution=DurationResolution.RELATIVEDELTA_FALLBACK)

        # update consumed words
        for idx, w in enumerate(_r.split()):
            if w == "_":
                remainder_words[idx + index + 1] = "_"

        if not delta:
            raise RuntimeError(
                "Could not extract duration from: " + duration_str)
        _date_str = " ".join(date_words[:index])
        _anchor_date, _r = extract_date_en(_date_str, ref_date)
        if not _anchor_date and len(date_words) > index + 1:
            _year = date_words[index + 1]
            if len(_year) == 4 and is_numeric(_year):
                _anchor_date = date(day=1, month=1, year=int(_year))
                remainder_words[index + 1] = ""
        else:
            # update consumed words
            for idx, w in enumerate(_r.split()):
                if w == "_":
                    remainder_words[idx] = "_"

        ref_date = _anchor_date or ref_date
        remainder_words[index] = "_"

    # relative timedelta found
    if delta and not date_found:
        try:
            if is_past or is_subtract:
                extracted_date = ref_date - delta
            else:
                extracted_date = ref_date + delta

            date_found = True
        except OverflowError:
            # TODO how to handle BC dates
            # https://stackoverflow.com/questions/15857797/bc-dates-in-python
            if is_past or is_subtract:
                year_bc = delta.days // DAYS_IN_1_YEAR - ref_date.year
                bc_str = str(year_bc) + " BC"
                print("ERROR: extracted date is " + bc_str)
            else:
                print("ERROR: extracted date is too far in the future")
            raise

    # iterate the word list to extract a date
    if not date_found:
        current_date = now_local()
        final_date = False

        # parse {era_name} -> reference_date
        # "common era", "after christ"
        for idx, word in enumerate(date_words):
            if word in eras:
                ref_date = eras[word]
                date_found = True
                remainder_words[idx] = ""

        extracted_date = ref_date

        for idx, word in enumerate(date_words):
            if final_date:
                break  # no more date updates allowed

            if word == "":
                continue

            wordPrevPrev = date_words[idx - 2] if idx > 1 else ""
            wordPrev = date_words[idx - 1] if idx > 0 else ""
            wordNext = date_words[idx + 1] if idx + 1 < len(date_words) else ""
            wordNextNext = date_words[idx + 2] if idx + 2 < len(
                date_words) else ""
            wordNextNextNext = date_words[idx + 3] if idx + 3 < len(
                date_words) else ""

            # parse "now"
            if word in now:
                date_found = True
                extracted_date = current_date
                remainder_words[idx] = ""
            # parse "today"
            if word in today:
                date_found = True
                extracted_date = ref_date
                remainder_words[idx] = ""
            # parse "yesterday"
            if word in yesterday:
                date_found = True
                extracted_date = ref_date - timedelta(days=1)
                remainder_words[idx] = ""
            # parse "tomorrow"
            if word in tomorrow:
                date_found = True
                extracted_date = ref_date + timedelta(days=1)
                remainder_words[idx] = ""
            # parse {weekday}
            if weekday_to_int(word, "en"):
                date_found = True
                int_week = weekday_to_int(word, "en")
                _w = extracted_date.weekday()
                _delta = 0
                if wordPrev in past_markers:
                    # parse last {weekday}
                    if int_week == _w:
                        _delta = 7
                    elif int_week < _w:
                        _delta = _w - int_week
                    else:
                        _delta = 7 - int_week + _w
                    extracted_date -= timedelta(days=_delta)

                    remainder_words[idx - 1] = ""
                else:
                    # parse this {weekday}
                    # parse next {weekday}
                    if int_week < _w:
                        _delta = 7 - _w + int_week
                    else:
                        _delta = int_week - _w
                    extracted_date += timedelta(days=_delta)

                    if wordPrev in this or wordPrev in future_markers:
                        remainder_words[idx - 1] = ""

                assert extracted_date.weekday() == int_week
                remainder_words[idx] = ""

            # parse {month}
            if month_to_int(word, "en"):
                date_found = True
                int_month = month_to_int(word, "en")

                extracted_date = ref_date.replace(month=int_month, day=1)

                if wordPrev in past_markers:
                    if int_month > ref_date.month:
                        extracted_date = extracted_date.replace(
                            year=ref_date.year - 1)
                    remainder_words[idx - 1] = ""
                elif wordPrev in future_markers:
                    if int_month < ref_date.month:
                        extracted_date = extracted_date.replace(
                            year=ref_date.year + 1)
                    remainder_words[idx - 1] = ""

                # parse {month} {DAY_OF_MONTH}
                if is_numeric(wordNext) and 0 < int(wordNext) <= 31:
                    extracted_date = extracted_date.replace(day=int(wordNext))
                    remainder_words[idx + 1] = ""
                    # parse {month} {DAY_OF_MONTH} {YYYY}
                    if resolution == DateTimeResolution.BEFORE_PRESENT and \
                            is_numeric(wordNextNext):
                        _year = get_date_ordinal(
                            int(wordNextNext), extracted_date,
                            DateTimeResolution.BEFORE_PRESENT_YEAR).year
                        extracted_date = extracted_date.replace(year=_year)
                        remainder_words[idx + 2] = ""
                    elif len(wordNextNext) == 4 and is_numeric(wordNextNext):
                        _year = int(wordNextNext)
                        extracted_date = extracted_date.replace(year=_year)
                        remainder_words[idx + 2] = ""

                # parse {DAY_OF_MONTH} {month}
                elif is_numeric(wordPrev) and 0 < int(wordPrev) <= 31:
                    extracted_date = extracted_date.replace(day=int(wordPrev))
                    remainder_words[idx - 1] = ""

                # parse {month} {YYYY}
                if len(wordNext) == 4 and is_numeric(wordNext):
                    extracted_date = extracted_date.replace(year=int(wordNext))
                    remainder_words[idx + 1] = ""

                # parse {YYYY} {month}
                elif len(wordPrev) == 4 and is_numeric(wordPrev):
                    extracted_date = extracted_date.replace(year=int(wordPrev))
                    remainder_words[idx - 1] = ""

                remainder_words[idx] = ""
            # parse "season"
            if word in season_literal:
                _start, _end = get_season_range(ref_date,
                                                hemisphere=hemisphere)
                # parse "in {Number} seasons"
                if is_numeric(wordPrev):
                    date_found = True
                    remainder_words[idx - 1] = ""
                    raise NotImplementedError
                # parse "this season"
                elif wordPrev in this:
                    date_found = True
                    extracted_date = _start
                    remainder_words[idx - 1] = ""
                # parse "last season"
                elif wordPrev in past_markers:
                    date_found = True
                    _end = _start - timedelta(days=2)
                    s = date_to_season(_end, hemisphere)
                    extracted_date = last_season_date(s, ref_date, hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "next season"
                elif wordPrev in future_markers:
                    date_found = True
                    extracted_date = _end + timedelta(days=1)
                    remainder_words[idx - 1] = ""
                # parse "mid season"
                elif wordPrev in mid:
                    date_found = True
                    extracted_date = _start + (_end - _start) / 2
                    remainder_words[idx - 1] = ""

                remainder_words[idx] = ""
            # parse "spring"
            if word in _SEASONS_EN[Season.SPRING]:
                date_found = True
                # parse "in {Number} springs"
                if is_numeric(wordPrev):
                    remainder_words[idx - 1] = ""
                    raise NotImplementedError
                # parse "last spring"
                elif wordPrev in past_markers:
                    extracted_date = last_season_date(Season.SPRING,
                                                      ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "next spring"
                elif wordPrev in future_markers:
                    extracted_date = next_season_date(Season.SPRING,
                                                      ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""

                else:
                    # parse "[this] spring"
                    extracted_date = season_to_date(Season.SPRING,
                                                    ref_date,
                                                    hemisphere)
                    if wordPrev in this:
                        remainder_words[idx - 1] = ""
                    # parse "mid {season}"
                    elif wordPrev in mid:
                        _start, _end = get_season_range(extracted_date)
                        extracted_date = _start + (_end - _start) / 2
                        remainder_words[idx - 1] = ""

                remainder_words[idx] = ""
            # parse "fall"
            if word in _SEASONS_EN[Season.FALL]:
                date_found = True
                # parse "in {Number} falls"
                if is_numeric(wordPrev):
                    remainder_words[idx - 1] = ""
                    raise NotImplementedError
                # parse "last fall"
                elif wordPrev in past_markers:
                    extracted_date = last_season_date(Season.FALL, ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "next fall"
                elif wordPrev in future_markers:
                    extracted_date = next_season_date(Season.FALL, ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "[this] fall"
                else:
                    extracted_date = season_to_date(Season.FALL,
                                                    ref_date,
                                                    hemisphere)
                    if wordPrev in this:
                        remainder_words[idx - 1] = ""
                    # parse "mid {season}"
                    elif wordPrev in mid:
                        _start, _end = get_season_range(extracted_date)
                        extracted_date = _start + (_end - _start) / 2
                        remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "summer"
            if word in _SEASONS_EN[Season.SUMMER]:
                date_found = True
                # parse "in {Number} summers"
                if is_numeric(wordPrev):
                    remainder_words[idx - 1] = ""
                    raise NotImplementedError
                # parse "last summer"
                elif wordPrev in past_markers:
                    extracted_date = last_season_date(Season.SUMMER, ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "next summer"
                elif wordPrev in future_markers:
                    extracted_date = next_season_date(Season.SUMMER, ref_date,
                                                      hemisphere)
                    remainder_words[idx - 1] = ""
                # parse "[this] summer"
                else:
                    extracted_date = season_to_date(Season.SUMMER,
                                                    ref_date,
                                                    hemisphere)
                    if wordPrev in this:
                        remainder_words[idx - 1] = ""
                    # parse "mid {season}"
                    elif wordPrev in mid:
                        _start, _end = get_season_range(extracted_date)
                        extracted_date = _start + (_end - _start) / 2
                        remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "winter"
            if word in _SEASONS_EN[Season.WINTER]:
                date_found = True
                # parse "in {Number} winters"
                if is_numeric(wordPrev):
                    remainder_words[idx - 1] = ""
                    raise NotImplementedError
                # parse "last winter"
                elif wordPrev in past_markers:
                    remainder_words[idx - 1] = ""
                    extracted_date = last_season_date(Season.WINTER, ref_date,
                                                      hemisphere)
                # parse "next winter"
                elif wordPrev in future_markers:
                    remainder_words[idx - 1] = ""
                    extracted_date = next_season_date(Season.WINTER, ref_date,
                                                      hemisphere)
                # parse "[this] winter"
                else:
                    extracted_date = season_to_date(Season.WINTER,
                                                    ref_date,
                                                    hemisphere)
                    if wordPrev in this:
                        remainder_words[idx - 1] = ""
                    # parse "mid {season}"
                    elif wordPrev in mid:
                        _start, _end = get_season_range(extracted_date)
                        extracted_date = _start + (_end - _start) / 2
                        remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "day"
            if word in day_literal:
                # parse {ORDINAL} day
                if is_numeric(wordPrev):
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(int(wordPrev),
                                                          ref_date,
                                                          DateTimeResolution.BEFORE_PRESENT_DAY)
                    else:
                        extracted_date = extracted_date.replace(
                            day=int(wordPrev))
                    remainder_words[idx - 1] = ""
                # parse day {NUMBER}
                elif is_numeric(wordNext):
                    date_found = True
                    extracted_date = extracted_date.replace(day=int(wordNext))
                    remainder_words[idx + 1] = ""
                # parse "present day"
                elif wordPrev in this:
                    date_found = True
                    extracted_date = ref_date
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "weekend"
            if word in weekend_literal:
                _is_weekend = ref_date.weekday() >= 5
                # parse {ORDINAL} weekend
                if is_numeric(wordPrev):
                    date_found = True
                    remainder_words[idx - 1] = ""
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev),
                            resolution=DateTimeResolution.BEFORE_PRESENT_WEEKEND)
                    else:
                        raise NotImplementedError
                # parse weekend {NUMBER}
                elif is_numeric(wordNext):
                    date_found = True
                    remainder_words[idx + 1] = ""
                    raise NotImplementedError
                # parse "this weekend"
                elif wordPrev in this:
                    date_found = True
                    extracted_date, _end = get_weekend_range(ref_date)
                    remainder_words[idx - 1] = ""
                # parse "next weekend"
                elif wordPrev in future_markers:
                    date_found = True
                    if not _is_weekend:
                        extracted_date, _end = get_weekend_range(ref_date)
                    else:
                        extracted_date, _end = get_weekend_range(ref_date +
                                                                 timedelta(
                                                                     weeks=1))
                    remainder_words[idx - 1] = ""
                # parse "last weekend"
                elif wordPrev in past_markers:
                    date_found = True
                    extracted_date, _end = get_weekend_range(ref_date -
                                                             timedelta(
                                                                 weeks=1))
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "week"
            if word in week_literal:
                # parse {ORDINAL} week
                if is_numeric(wordPrev) and 0 < int(wordPrev) <= 4 * 12:
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        _week = get_date_ordinal(
                            int(wordPrev),
                            resolution=DateTimeResolution.BEFORE_PRESENT_WEEK)
                    else:
                        _week = get_date_ordinal(int(wordPrev), ref_date,
                                                 resolution=DateTimeResolution.WEEK_OF_YEAR)
                    extracted_date, _end = get_week_range(_week)
                    remainder_words[idx - 1] = ""
                # parse "this week"
                if wordPrev in this:
                    date_found = True
                    extracted_date, _end = get_week_range(ref_date)
                    remainder_words[idx - 1] = ""
                # parse "last week"
                elif wordPrev in past_markers:
                    date_found = True
                    _last_week = ref_date - timedelta(weeks=1)
                    extracted_date, _end = get_week_range(_last_week)
                    remainder_words[idx - 1] = ""
                # parse "next week"
                elif wordPrev in future_markers:
                    date_found = True
                    _last_week = ref_date + timedelta(weeks=1)
                    extracted_date, _end = get_week_range(_last_week)
                    remainder_words[idx - 1] = ""
                # parse week {NUMBER}
                elif is_numeric(wordNext) and 0 < int(wordNext) <= 12:
                    date_found = True
                    extracted_date = get_date_ordinal(int(wordNext), ref_date,
                                                      resolution=DateTimeResolution.WEEK_OF_YEAR)
                    remainder_words[idx + 1] = ""
                remainder_words[idx] = ""
            # parse "month"
            if word in month_literal:

                # parse {ORDINAL} month
                if is_numeric(wordPrev) and 0 < int(wordPrev) <= 12:
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev),
                            resolution=DateTimeResolution.BEFORE_PRESENT_MONTH)
                    else:
                        extracted_date = get_date_ordinal(int(wordPrev),
                                                          ref_date,
                                                          DateTimeResolution.MONTH_OF_YEAR)
                    remainder_words[idx - 1] = ""
                # parse month {NUMBER}
                elif is_numeric(wordNext) and 0 < int(wordNext) <= 12:
                    date_found = True
                    extracted_date = get_date_ordinal(int(wordNext), ref_date,
                                                      DateTimeResolution.MONTH_OF_YEAR)
                    remainder_words[idx - 1] = ""
                # parse "this month"
                elif wordPrev in this:
                    date_found = True
                    extracted_date = ref_date.replace(day=1)
                    remainder_words[idx - 1] = ""
                # parse "next month"
                elif wordPrev in future_markers:
                    date_found = True
                    _next_month = ref_date + timedelta(days=DAYS_IN_1_MONTH)
                    extracted_date = _next_month.replace(day=1)
                    remainder_words[idx - 1] = ""
                # parse "last month"
                elif wordPrev in past_markers:
                    date_found = True
                    _last_month = ref_date - timedelta(days=DAYS_IN_1_MONTH)
                    extracted_date = _last_month.replace(day=1)
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "year"
            if word in year_literal:
                # parse "current year"
                if wordPrev in this:
                    date_found = True
                    extracted_date = get_date_ordinal(ref_date.year,
                                                      resolution=DateTimeResolution.YEAR)
                    remainder_words[idx - 1] = ""
                # parse "last year"
                elif wordPrev in past_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(ref_date.year - 1,
                                                      resolution=DateTimeResolution.YEAR)
                    remainder_words[idx - 1] = ""
                # parse "next year"
                elif wordPrev in future_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(ref_date.year + 1,
                                                      resolution=DateTimeResolution.YEAR)
                    remainder_words[idx - 1] = ""
                # parse Nth year
                elif is_numeric(wordPrev):
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev),
                            resolution=DateTimeResolution.BEFORE_PRESENT_YEAR)
                    else:
                        extracted_date = get_date_ordinal(
                            int(wordPrev) - 1,
                            resolution=DateTimeResolution.YEAR)
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "decade"
            if word in decade_literal:
                _decade = (ref_date.year // 10) + 1
                # parse "current decade"
                if wordPrev in this:
                    date_found = True
                    extracted_date = get_date_ordinal(_decade,
                                                      resolution=DateTimeResolution.DECADE)
                    remainder_words[idx - 1] = ""
                # parse "last decade"
                elif wordPrev in past_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_decade - 1,
                                                      resolution=DateTimeResolution.DECADE)
                    remainder_words[idx - 1] = ""
                # parse "next decade"
                elif wordPrev in future_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_decade + 1,
                                                      resolution=DateTimeResolution.DECADE)
                    remainder_words[idx - 1] = ""
                # parse Nth decade
                elif is_numeric(wordPrev):
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev),
                            resolution=DateTimeResolution.BEFORE_PRESENT_DECADE)
                    else:
                        extracted_date = get_date_ordinal(int(wordPrev),
                                                          resolution=DateTimeResolution.DECADE)
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "millennium"
            if word in millennium_literal:
                _mil = (ref_date.year // 1000) + 1
                # parse "current millennium"
                if wordPrev in this:
                    date_found = True
                    extracted_date = get_date_ordinal(_mil, ref_date,
                                                      DateTimeResolution.MILLENNIUM)
                    remainder_words[idx - 1] = ""
                # parse "last millennium"
                elif wordPrev in past_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_mil - 1, ref_date,
                                                      DateTimeResolution.MILLENNIUM)
                    remainder_words[idx - 1] = ""
                # parse "next millennium"
                elif wordPrev in future_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_mil + 1, ref_date,
                                                      DateTimeResolution.MILLENNIUM)
                    remainder_words[idx - 1] = ""
                # parse Nth millennium
                elif is_numeric(wordPrev):
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev), extracted_date,
                            DateTimeResolution.BEFORE_PRESENT_MILLENNIUM)
                    else:
                        extracted_date = get_date_ordinal(
                            int(wordPrev), extracted_date,
                            DateTimeResolution.MILLENNIUM)
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse "century"
            if word in century_literal:
                _century = (ref_date.year // 100) + 1
                # parse "current century"
                if wordPrev in this:
                    date_found = True
                    extracted_date = get_date_ordinal(_century, ref_date,
                                                      DateTimeResolution.CENTURY)
                    remainder_words[idx - 1] = ""
                # parse "last century"
                elif wordPrev in past_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_century - 1,
                                                      ref_date,
                                                      DateTimeResolution.CENTURY)
                    remainder_words[idx - 1] = ""
                # parse "next century"
                elif wordPrev in future_markers:
                    date_found = True
                    extracted_date = get_date_ordinal(_century + 1,
                                                      ref_date,
                                                      DateTimeResolution.CENTURY)
                    remainder_words[idx - 1] = ""
                # parse Nth century
                elif is_numeric(wordPrev):
                    date_found = True
                    if resolution == DateTimeResolution.BEFORE_PRESENT:
                        extracted_date = get_date_ordinal(
                            int(wordPrev), extracted_date,
                            DateTimeResolution.BEFORE_PRESENT_CENTURY)
                    else:
                        extracted_date = get_date_ordinal(int(wordPrev),
                                                          extracted_date,
                                                          DateTimeResolution.CENTURY)
                    remainder_words[idx - 1] = ""
                remainder_words[idx] = ""
            # parse {holiday_name}
            if word in named_dates:
                extracted_date = named_dates[word]
                date_found = True
                remainder_words[idx] = ""
                # parse "this christmas"
                if wordPrev in this:
                    remainder_words[idx - 1] = ""
                # parse "last christmas"
                elif wordPrev in past_markers:
                    date_found = True
                    # TODO check if current year or previous
                    if True:
                        raise NotImplementedError
                        extracted_date -= relativedelta(years=1)
                    remainder_words[idx - 1] = ""
                # parse "next christmas"
                elif wordPrev in future_markers:
                    date_found = True
                    # TODO check if current year or previous
                    if True:
                        raise NotImplementedError
                        extracted_date += relativedelta(years=1)
                    remainder_words[idx - 1] = ""
                # parse Nth christmas
                elif is_numeric(wordPrev):
                    date_found = True
                    extracted_date += relativedelta(years=int(wordPrev))
                    remainder_words[idx - 1] = ""
            # parse "easter"
            if word in easter_literal:
                date_found = True
                remainder_words[idx] = ""
                # parse "last easter"
                if wordPrev in past_markers:
                    date_found = True
                    # TODO check if current year or previous
                    if True:
                        raise NotImplementedError
                        _year = ref_date - relativedelta(years=1)
                        if _year.year < 1583:
                            method = 1
                        else:
                            method = 3
                        extracted_date = easter(_year.year, method)
                    remainder_words[idx - 1] = ""
                # parse "next easter"
                elif wordPrev in future_markers:
                    date_found = True
                    # TODO check if current year or previous
                    if True:
                        raise NotImplementedError
                        _year = ref_date + relativedelta(years=1)
                        if _year.year < 1583:
                            method = 1
                        else:
                            method = 3
                        extracted_date = easter(_year.year, method)
                    remainder_words[idx - 1] = ""
                # parse Nth easter
                elif is_numeric(wordPrev):
                    date_found = True
                    _year = ref_date.year + int(wordPrev)
                    if _year < 1583:
                        method = 1
                    else:
                        method = 3
                    extracted_date = easter(_year, method)
                    remainder_words[idx - 1] = ""
                else:
                    # parse "this easter"
                    if wordPrev in this:
                        remainder_words[idx - 1] = ""
                    if ref_date.year < 1583:
                        method = 1
                    else:
                        method = 3
                    extracted_date = easter(ref_date.year, method)
            # parse day/mont/year is NUMBER
            if word in set_qualifiers and is_numeric(wordNext):
                _ordinal = int(wordNext)
                if wordPrev in day_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.DAY_OF_MONTH)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                elif wordPrev in month_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.MONTH_OF_YEAR)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                elif wordPrev in year_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.YEAR)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                elif wordPrev in decade_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.DECADE)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                elif wordPrev in century_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.CENTURY)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                elif wordPrev in millennium_literal:
                    date_found = True
                    extracted_date = get_date_ordinal(_ordinal, extracted_date,
                                                      DateTimeResolution.MILLENNIUM)
                    remainder_words[idx - 1] = ""
                    remainder_words[idx + 1] = ""
                    remainder_words[idx] = ""
                    # TODO week of month vs week of year
            # parse {date} at {location}
            if word in location_markers:
                # this is used to parse seasons, which depend on
                # geographical location
                # "i know what you did last summer",  "winter is coming"
                # usually the default will be set automatically based on user
                # location

                # NOTE these words are kept in the utterance remainder
                # they are helpers but not part of the date itself

                # parse {date} at north hemisphere
                if wordNext in _HEMISPHERES_EN[Hemisphere.NORTH] and \
                        wordNextNext in hemisphere_literal:
                    hemisphere = Hemisphere.NORTH
                # parse {date} at south hemisphere
                elif wordNext in _HEMISPHERES_EN[Hemisphere.SOUTH] and \
                        wordNextNext in hemisphere_literal:
                    hemisphere = Hemisphere.SOUTH
                # parse {date} at {country/city}
                elif _ner is not None:
                    # parse string for Country names
                    for r in _ner.extract_entities(wordNext):
                        if r.entity_type == "Country":
                            if r.data["latitude"] < 0:
                                hemisphere = Hemisphere.SOUTH
                            else:
                                hemisphere = Hemisphere.NORTH
                    else:
                        #  or Capital city names
                        for r in _ner.extract_entities(wordNext):
                            if r.entity_type == "Capital City":
                                if r.data["hemisphere"].startswith("s"):
                                    hemisphere = Hemisphere.SOUTH
                                else:
                                    hemisphere = Hemisphere.NORTH

            # bellow we parse standalone numbers, this is the major source
            # of ambiguity, caution advised

            # NOTE this is the place to check for requested
            # DateTimeResolution, usually not requested by the user but
            # rather used in recursion inside this very same method

            # NOTE2: the checks for XX_literal above may also need to
            # account for DateTimeResolution when parsing {Ordinal} {unit},
            # bellow refers only to default/absolute units

            # parse {YYYY} before present
            if not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.BEFORE_PRESENT:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.BEFORE_PRESENT_YEAR)
            # parse {N} unix time
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.UNIX:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.UNIX_SECOND)
            # parse {N} julian days (since 1 January 4713 BC)
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.JULIAN:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.JULIAN_DAY)
            # parse {N} ratadie (days since 1/1/1)
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.RATADIE:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.RATADIE_DAY)
            # parse {YYYY} common era (years since 1/1/1)
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.CE:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.CE_YEAR)
            # parse {N} lilian days
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.LILIAN:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.LILIAN_DAY)
            # parse {YYYYY} holocene year
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.HOLOCENE:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.HOLOCENE_YEAR)
            # parse {YYYYY} After the Development of Agriculture (ADA)
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.ADA:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.ADA_YEAR)
            # parse {YYYYY} "Creation Era of Constantinople"/"Era of the World"
            elif not date_found and is_numeric(word) and resolution == \
                    DateTimeResolution.CEC:
                date_found = True
                extracted_date = get_date_ordinal(
                    int(word), extracted_date,
                    DateTimeResolution.CEC_YEAR)
            # parse {YYYY}
            # NOTE: assumes a full date has at least 3 digits
            elif greedy and is_numeric(word) and len(word) >= 3 \
                    and wordPrev not in day_literal + week_literal + \
                    weekend_literal + month_literal + decade_literal + \
                    century_literal + millennium_literal \
                    and wordNext not in day_literal + week_literal + \
                    weekend_literal + month_literal + decade_literal + \
                    century_literal + millennium_literal:
                date_found = True
                extracted_date = extracted_date.replace(year=int(word))
                remainder_words[idx] = ""

            # parse 19{YY} / 20{YY}
            # NOTE: assumes past or current century
            elif greedy and is_numeric(word) \
                    and wordPrev not in day_literal + week_literal + \
                    weekend_literal + month_literal + decade_literal + \
                    century_literal + millennium_literal \
                    and wordNext not in day_literal + week_literal + \
                    weekend_literal + month_literal + decade_literal + \
                    century_literal + millennium_literal:
                date_found = True
                _year = int(word)
                _base = (ref_date.year // 100) * 100
                _delta = int(str(ref_date.year)[-2:])
                if _delta > _year:
                    # year belongs to current century
                    # 13 -> 2013
                    _year = _base + _year
                else:
                    # year belongs to last century
                    # 69 -> 1969
                    _year = _base - 100 + _year

                extracted_date = extracted_date.replace(year=_year)
                remainder_words[idx] = ""
            # parse {year} {era}
            # "1992 after christ"
            elif is_numeric(word) and wordNext in eras:
                date_found = True
                extracted_date = extracted_date.replace(year=int(word))
                remainder_words[idx] = ""
            # parse "the {YYYY}s"
            elif not is_numeric(word) and is_numeric(word.rstrip("s")):
                date_found = True
                _year = word.rstrip("s")
                if len(_year) == 2:
                    _base = (ref_date.year // 100) * 100
                    _delta = int(str(ref_date.year)[-2:])
                    if _delta > int(_year):
                        # year belongs to current century
                        # 13 -> 2013
                        _year = _base + int(_year)
                    else:
                        # year belongs to last century
                        # 69 -> 1969
                        _year = _base - 100 + int(_year)
                else:
                    _year = int(_year)
                extracted_date = extracted_date.replace(year=_year)
                remainder_words[idx] = ""

    remainder = " ".join([w or "_" for w in remainder_words])
    # print(date_str, "//", remainder)

    if date_found:
        if isinstance(extracted_date, datetime):
            extracted_date = extracted_date.date()
        return extracted_date, remainder
    return None, date_str
