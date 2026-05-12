/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#include "Balance.hpp"
#include "decimal.hpp"

#include <gmock/gmock.h>
#include <gtest/gtest.h>

//-------------------------------------------------------------------------

using taosim::decimal_t;
using namespace taosim::accounting;
using namespace testing;

//-------------------------------------------------------------------------

struct InitTest : public TestWithParam<std::pair<decimal_t, decimal_t>> 
{
    virtual void SetUp() override
    {
        const auto [totalBalance, maxLeverage] = GetParam();
        this->totalBalance = totalBalance;
        this->maxLeverage = maxLeverage;
    }

    decimal_t totalBalance;
    decimal_t maxLeverage;
};

INSTANTIATE_TEST_SUITE_P(
    BalanceTest, 
    InitTest,
    Values(
        std::pair{0_dec, 0_dec},
        std::pair{42_dec, 0_dec},
        std::pair{-322_dec, 0_dec},
        std::pair{420_dec, 0_dec},
        std::pair{-1337_dec, 0_dec},
        std::pair{9000_dec, 0_dec},
        std::pair{0_dec, 5_dec},
        std::pair{42_dec, -2_dec},
        std::pair{-322_dec, 3_dec},
        std::pair{420_dec, 1_dec},
        std::pair{-1337_dec, 2_dec},
        std::pair{9000_dec, -5_dec}));

TEST_P(InitTest, WorksCorrectly)
{
    if (totalBalance < 0_dec) {
        EXPECT_THROW(Balance{totalBalance}, std::invalid_argument);
        return;
    }
    if (maxLeverage < 0_dec) {
        EXPECT_THROW((Balance{totalBalance, maxLeverage}), std::invalid_argument);
        return;
    }

    const auto balance = Balance{totalBalance, maxLeverage};
    EXPECT_EQ(balance.getFree(), totalBalance);
    EXPECT_EQ(balance.getTotal(), totalBalance);
    EXPECT_EQ(balance.getActualTotal(), totalBalance);
    EXPECT_EQ(balance.getVirtualTotal(), 0_dec);
    EXPECT_EQ(balance.getReserved(), 0_dec);
    EXPECT_EQ(balance.getActualReserved(), 0_dec);
    EXPECT_EQ(balance.getVirtualReserved(), 0_dec);
}

//-------------------------------------------------------------------------

struct ReserveTest : public TestWithParam<std::tuple<decimal_t, decimal_t, decimal_t>>
{
    virtual void SetUp() override
    {
        const auto [totalBalance, toBeReserved, lev] = GetParam();
        this->balance = Balance{totalBalance, maxLev}; // maxLeverage = 3
        this->nRoundDec = this->balance.getLoan().m_params.volumeIncrementDecimals;
        this->totalBalance = totalBalance;
        this->lev = lev;
        this->toBeReserved = toBeReserved * (1_dec + lev);
        this->actualReserved = toBeReserved;
        // this->toBeReserved = toBeReserved;
        // this->actualReserved = taosim::util::round(toBeReserved / (1_dec + lev), nRoundDec);
        // this->actualReserved = toBeReserved / (1_dec + lev);
    }

    const decimal_t maxLev = 3_dec;
    Balance balance; 
    decimal_t totalBalance;
    decimal_t toBeReserved;
    decimal_t actualReserved;
    decimal_t lev;
    uint32_t nRoundDec;
    OrderID orderId{};
};

INSTANTIATE_TEST_SUITE_P(
    BalanceTest,
    ReserveTest,
    Values(
        std::tuple{100_dec, 42_dec, 0_dec},
        std::tuple{500_dec, 322_dec, 0_dec},
        std::tuple{1000_dec, 420_dec, 0_dec},
        std::tuple{5000_dec, 1337_dec, 0_dec},
        std::tuple{10'000_dec, 9000_dec, 0_dec},
        std::tuple{100_dec, -42_dec, 1_dec},
        std::tuple{300_dec, 322_dec, DEC(1.5)},
        std::tuple{500_dec, -420_dec, DEC(0.5)},
        std::tuple{8999_dec, 9000_dec, 2_dec},
        std::tuple{100_dec, 42_dec, 1_dec},
        std::tuple{500_dec, 322_dec, 3_dec},
        std::tuple{1000_dec, 420_dec, 4_dec},
        std::tuple{5000_dec, 1337_dec, 2_dec},
        std::tuple{10'000_dec, 9000_dec, -2_dec}
        ));

TEST_P(ReserveTest, WorksCorrectly)
{

    if (toBeReserved < 0_dec || actualReserved > balance.getFree()) {
        EXPECT_FALSE(balance.canReserve(toBeReserved, lev));
        EXPECT_THROW(balance.makeReservation(orderId, toBeReserved, lev), std::invalid_argument);
        return;
    }
    if (lev < 0_dec || lev > 3_dec) {
        EXPECT_FALSE(balance.canReserve(toBeReserved, lev));
        EXPECT_THROW(balance.makeReservation(orderId, toBeReserved, lev), std::invalid_argument);
        return;
    }

    EXPECT_TRUE(balance.canReserve(toBeReserved, lev));
    EXPECT_NO_THROW(balance.makeReservation(orderId, toBeReserved, lev));
    EXPECT_EQ(balance.getMaxLeverage(), maxLev);
    EXPECT_EQ(balance.getFree(), taosim::util::round(totalBalance - actualReserved, nRoundDec));
    EXPECT_EQ(balance.getTotal(), taosim::util::round(totalBalance + actualReserved * lev, nRoundDec));
    EXPECT_EQ(balance.getActualTotal(), taosim::util::round(totalBalance, nRoundDec));
    EXPECT_EQ(balance.getVirtualTotal(), taosim::util::round(actualReserved * lev, nRoundDec));
    EXPECT_EQ(balance.getReserved(), taosim::util::round(toBeReserved, nRoundDec));
    EXPECT_EQ(balance.getActualReserved(), taosim::util::round(actualReserved, nRoundDec));
    EXPECT_EQ(balance.getVirtualReserved(), taosim::util::round(actualReserved * lev, nRoundDec));
    EXPECT_THAT(balance.getReservation(orderId), Optional(taosim::util::round(toBeReserved, nRoundDec)));
    EXPECT_THAT(balance.getActualReservation(orderId), Optional(taosim::util::round(actualReserved, nRoundDec)));
    EXPECT_THAT(balance.getVirtualReservation(orderId), Optional(taosim::util::round(actualReserved * lev, nRoundDec)));

}

//-------------------------------------------------------------------------

struct FreeTest : public TestWithParam<std::tuple<decimal_t, decimal_t, decimal_t, decimal_t>>
{
    virtual void SetUp() override
    {
        const auto [totalBalance, toBeReserved, toBeFreed, lev] = GetParam();
        balance = Balance{totalBalance, maxLev};
        roundingDecimals = balance.getLoan().m_params.volumeIncrementDecimals;
        this->totalBalance = totalBalance;
        this->toBeReserved = toBeReserved * (1_dec + lev);
        this->actualReserved = toBeReserved;
        this->toBeFreed = toBeFreed * (1_dec + lev);
        this->actualFreed = toBeFreed;
        this->lev = lev;
        balance.makeReservation(orderId, this->toBeReserved, this->lev);
        this->estimatedLev = taosim::util::round(balance.getVirtualReservation(orderId).value()/balance.getActualReservation(orderId).value(),
            roundingDecimals);
    }

    const decimal_t maxLev = 3_dec;
    uint32_t roundingDecimals;
    Balance balance;
    decimal_t totalBalance;
    decimal_t toBeReserved;
    decimal_t actualReserved;
    decimal_t toBeFreed;
    decimal_t actualFreed;
    decimal_t lev;
    decimal_t estimatedLev;
    OrderID orderId{};
};

INSTANTIATE_TEST_SUITE_P(
    BalanceTest,
    FreeTest,
    Values(
        std::tuple{100_dec, 50_dec, 42_dec, 0_dec},
        std::tuple{500_dec, 350_dec, 322_dec, 0_dec},
        std::tuple{1000_dec, 500_dec, 500_dec, 0_dec},
        std::tuple{10'000_dec, 9000_dec, 1000_dec, 0_dec},
        std::tuple{100_dec, 50_dec, 52_dec, 0_dec},
        std::tuple{500_dec, 350_dec, -400_dec, 0_dec},
        std::tuple{5_dec, DEC(2.92903307), DEC(2.92903307), 0_dec},
        std::tuple{100_dec, 50_dec, 42_dec, 1_dec},
        std::tuple{500_dec, 350_dec, 322_dec, DEC(0.5)},
        std::tuple{1000_dec, 500_dec, 500_dec, 2_dec},
        std::tuple{15'000_dec, 9000_dec, 1000_dec, 3_dec},
        std::tuple{100_dec, 50_dec, 52_dec, 1_dec},
        std::tuple{800_dec, 350_dec, -400_dec, DEC(0.2)},
        std::tuple{500_dec, 50_dec, 100_dec, 1_dec},
        std::tuple{5_dec, DEC(2.929), DEC(2.929), DEC(1.5)},
        std::tuple{10_dec, DEC(2.92903307), DEC(2.92903307), DEC(1.5)}));

TEST_P(FreeTest, WorksCorrectly)
{
    if (toBeFreed < 0_dec) {
        EXPECT_EQ(balance.canFree(orderId, toBeFreed).status, FreeStatus::NEGATIVE_AMOUNT);
        EXPECT_THROW(balance.freeReservation(orderId, toBeFreed), FreeException);
    }
    else if (toBeFreed > toBeReserved) {
        EXPECT_EQ(balance.canFree(orderId, toBeFreed).status, FreeStatus::AMOUNT_EXCEEDS_RESERVATION);
        EXPECT_THROW(balance.freeReservation(orderId, toBeFreed), FreeException);
        EXPECT_EQ(balance.getMaxLeverage(), maxLev);
        EXPECT_EQ(balance.getFree(), totalBalance - actualReserved);
        EXPECT_EQ(balance.getTotal(), totalBalance + actualReserved * lev);
        EXPECT_EQ(balance.getActualTotal(), totalBalance);
        EXPECT_EQ(balance.getVirtualTotal(), actualReserved * lev);
        EXPECT_EQ(balance.getReserved(), actualReserved * (1_dec + lev));
        EXPECT_EQ(balance.getActualReserved(), actualReserved);
        EXPECT_EQ(balance.getVirtualReserved(), actualReserved * lev);
        EXPECT_THAT(balance.getReservation(orderId), Optional(toBeReserved));
        EXPECT_THAT(balance.getActualReservation(orderId), Optional(actualReserved));
        EXPECT_THAT(balance.getVirtualReservation(orderId), Optional(actualReserved * lev));
    }
    else if (toBeFreed == toBeReserved) {
        EXPECT_EQ(balance.canFree(orderId, toBeFreed).status, FreeStatus::FREEABLE);
        EXPECT_NO_THROW(balance.freeReservation(orderId, toBeFreed));
        EXPECT_EQ(balance.getMaxLeverage(), maxLev);
        EXPECT_EQ(balance.getFree(), totalBalance);
        EXPECT_EQ(balance.getTotal(), totalBalance);
        EXPECT_EQ(balance.getActualTotal(), totalBalance);
        EXPECT_EQ(balance.getVirtualTotal(), 0_dec);
        EXPECT_EQ(balance.getReserved(), 0_dec);
        EXPECT_EQ(balance.getActualReserved(), 0_dec);
        EXPECT_EQ(balance.getVirtualReserved(), 0_dec);
        EXPECT_THAT(balance.getReservation(orderId), std::nullopt);
        EXPECT_THAT(balance.getActualReservation(orderId), std::nullopt);
        EXPECT_THAT(balance.getVirtualReservation(orderId), std::nullopt);
    }
    else {
        EXPECT_EQ(balance.canFree(orderId, toBeFreed).status, FreeStatus::FREEABLE);
        EXPECT_NO_THROW(balance.freeReservation(orderId, toBeFreed));
        EXPECT_EQ(balance.getMaxLeverage(), maxLev);
        EXPECT_EQ(balance.getFree(), taosim::util::round(totalBalance - actualReserved + actualFreed, roundingDecimals));
        EXPECT_EQ(balance.getTotal(), taosim::util::round(totalBalance + actualReserved * estimatedLev - toBeFreed + actualFreed, roundingDecimals));
        EXPECT_EQ(balance.getActualTotal(), totalBalance);
        EXPECT_EQ(balance.getVirtualTotal(), taosim::util::round(actualReserved * estimatedLev - toBeFreed + actualFreed, roundingDecimals));
        EXPECT_EQ(balance.getReserved(), taosim::util::round(toBeReserved - toBeFreed, roundingDecimals));
        EXPECT_EQ(balance.getActualReserved(), taosim::util::round(actualReserved - actualFreed, roundingDecimals));
        EXPECT_EQ(balance.getVirtualReserved(), taosim::util::round(actualReserved * estimatedLev - toBeFreed + actualFreed, roundingDecimals));
        EXPECT_THAT(balance.getReservation(orderId), Optional(taosim::util::round(toBeReserved - toBeFreed, roundingDecimals)));
        EXPECT_THAT(balance.getActualReservation(orderId), Optional(taosim::util::round(actualReserved - actualFreed, roundingDecimals)));
        EXPECT_THAT(balance.getVirtualReservation(orderId), Optional(taosim::util::round(actualReserved * estimatedLev - toBeFreed + actualFreed, roundingDecimals)));
    }
}

//-------------------------------------------------------------------------

struct DepositTest : public TestWithParam<std::pair<decimal_t, decimal_t>>
{
    virtual void SetUp() override
    {
        const auto [totalBalance, toBeDeposited] = GetParam();
        balance = Balance{totalBalance};
        this->totalBalance = totalBalance;
        this->toBeDeposited = toBeDeposited;
    }

    Balance balance;
    decimal_t totalBalance;
    decimal_t toBeDeposited;
};

INSTANTIATE_TEST_SUITE_P(
    BalanceTest,
    DepositTest,
    Values(
        std::pair{0_dec, 100_dec},
        std::pair{100_dec, 500_dec},
        std::pair{1000_dec, 2500_dec},
        std::pair{0_dec, -50_dec},
        std::pair{100_dec, -100_dec},
        std::pair{1000_dec, -1500_dec}));

TEST_P(DepositTest, WorksCorrectly)
{
    const auto endAmount = totalBalance + toBeDeposited;

    balance.deposit(toBeDeposited);

    if (endAmount < 0_dec) {
        EXPECT_EQ(balance.getFree(), 0_dec);
        EXPECT_EQ(balance.getTotal(), 0_dec);
        EXPECT_EQ(balance.getActualTotal(), 0_dec);
        EXPECT_EQ(balance.getVirtualTotal(), 0_dec);
        EXPECT_EQ(balance.getReserved(), 0_dec);
        EXPECT_EQ(balance.getActualReserved(), 0_dec);
        EXPECT_EQ(balance.getVirtualReserved(), 0_dec);
        return;
    }

    EXPECT_EQ(balance.getFree(), endAmount);
    EXPECT_EQ(balance.getTotal(), endAmount);
    EXPECT_EQ(balance.getActualTotal(), endAmount);
    EXPECT_EQ(balance.getVirtualTotal(), 0_dec);
    EXPECT_EQ(balance.getReserved(), 0_dec);
    EXPECT_EQ(balance.getActualReserved(), 0_dec);
    EXPECT_EQ(balance.getVirtualReserved(), 0_dec);
}

//-------------------------------------------------------------------------

struct MoveTest : public TestWithParam<std::tuple<decimal_t, decimal_t, decimal_t>>
{
    virtual void SetUp() override
    {
        const auto [totalBalance, toBeReservedFirst, toBeReservedSecond] = GetParam();
        balance = Balance{totalBalance, maxLev};
        this->totalBalance = totalBalance;
        this->toBeReservedFirst = toBeReservedFirst;
        this->toBeReservedSecond = toBeReservedSecond;
        this->actualReservedFirst = toBeReservedFirst;
        this->actualReservedSecond = toBeReservedSecond / 2_dec;
        balance.makeReservation(orderIdFirst, this->toBeReservedFirst, 0_dec);
        balance.makeReservation(orderIdSecond, this->toBeReservedSecond, 1_dec);
    }

    const decimal_t maxLev = 3_dec;
    Balance balance;
    decimal_t totalBalance;
    decimal_t toBeReservedFirst;
    decimal_t toBeReservedSecond;
    decimal_t actualReservedFirst;
    decimal_t actualReservedSecond;
    OrderID orderIdFirst{};
    OrderID orderIdSecond{1};
};

INSTANTIATE_TEST_SUITE_P(
    BalanceTest,
    MoveTest,
    Values(
        std::tuple{100_dec, 50_dec, 42_dec},
        std::tuple{500_dec, 350_dec, 100_dec},
        std::tuple{1000_dec, 500_dec, 500_dec},
        std::tuple{10'000_dec, 9000_dec, 1000_dec}));

TEST_P(MoveTest, WorksCorrectly)
{
    Balance movedBalance{std::move(balance)};

    EXPECT_EQ(balance.getMaxLeverage(), 0_dec);
    EXPECT_EQ(balance.getFree(), 0_dec);
    EXPECT_EQ(balance.getTotal(), 0_dec);
    EXPECT_EQ(balance.getActualTotal(), 0_dec);
    EXPECT_EQ(balance.getVirtualTotal(), 0_dec);
    EXPECT_EQ(balance.getReserved(), 0_dec);
    EXPECT_EQ(balance.getActualReserved(), 0_dec);
    EXPECT_EQ(balance.getVirtualReserved(), 0_dec);
    EXPECT_THAT(balance.getReservation(orderIdFirst), Eq(std::nullopt));
    EXPECT_THAT(balance.getActualReservation(orderIdFirst), Eq(std::nullopt));
    EXPECT_THAT(balance.getVirtualReservation(orderIdFirst), Eq(std::nullopt));
    EXPECT_THAT(balance.getReservation(orderIdSecond), Eq(std::nullopt));
    EXPECT_THAT(balance.getActualReservation(orderIdSecond), Eq(std::nullopt));
    EXPECT_THAT(balance.getVirtualReservation(orderIdSecond), Eq(std::nullopt));

    EXPECT_EQ(movedBalance.getMaxLeverage(), maxLev);
    EXPECT_EQ(movedBalance.getFree(), totalBalance - toBeReservedFirst - actualReservedSecond);
    EXPECT_EQ(movedBalance.getTotal(), totalBalance + actualReservedSecond);
    EXPECT_EQ(movedBalance.getActualTotal(), totalBalance);
    EXPECT_EQ(movedBalance.getVirtualTotal(), actualReservedSecond);
    EXPECT_EQ(movedBalance.getReserved(), toBeReservedFirst + toBeReservedSecond);
    EXPECT_EQ(movedBalance.getActualReserved(), toBeReservedFirst + actualReservedSecond);
    EXPECT_EQ(movedBalance.getVirtualReserved(), actualReservedSecond);
    EXPECT_THAT(movedBalance.getReservation(orderIdFirst), toBeReservedFirst);
    EXPECT_THAT(movedBalance.getActualReservation(orderIdFirst), toBeReservedFirst);
    EXPECT_THAT(movedBalance.getVirtualReservation(orderIdFirst), 0_dec);
    EXPECT_THAT(movedBalance.getReservation(orderIdSecond), toBeReservedSecond);
    EXPECT_THAT(movedBalance.getActualReservation(orderIdSecond), actualReservedSecond);
    EXPECT_THAT(movedBalance.getVirtualReservation(orderIdSecond), actualReservedSecond);
}

//-------------------------------------------------------------------------
