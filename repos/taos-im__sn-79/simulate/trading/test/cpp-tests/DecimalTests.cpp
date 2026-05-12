/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#include "decimal.hpp"

#include <gmock/gmock.h>
#include <gtest/gtest.h>

//-------------------------------------------------------------------------

using namespace testing;
using namespace taosim;

//-------------------------------------------------------------------------

struct PackUnpackTest : TestWithParam<decimal_t> {};

INSTANTIATE_TEST_SUITE_P(
    DecimalTest,
    PackUnpackTest,
    Values(
        DEC(0.0),
        DEC(1.337),
        DEC(32.2),
        DEC(42.0),
        DEC(69420.0),
        DEC(1.234567890123456e-42)));

TEST_P(PackUnpackTest, ValuesMatch)
{
    const decimal_t packee = GetParam();
    const uint64_t packed = util::packDecimal(packee);
    const decimal_t unpacked = util::unpackDecimal(packed);
    EXPECT_EQ(packee, unpacked);
}

//-------------------------------------------------------------------------
