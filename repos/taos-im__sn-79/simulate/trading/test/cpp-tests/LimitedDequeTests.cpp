/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#include "LimitedDeque.hpp"

#include "common.hpp"

#include <gmock/gmock.h>
#include <gtest/gtest.h>

//-------------------------------------------------------------------------

TEST(LimitedDequeTest, PushBack)
{
    static constexpr size_t capacity = 5;

    LimitedDeque<uint32_t> deque{capacity};

    for (uint32_t i : views::iota(0u, capacity)) {
        deque.push_back(i);
    }

    EXPECT_THAT(
        deque,
        testing::ElementsAreArray(views::iota(0u, capacity) | ranges::to<std::vector>()));
}

//-------------------------------------------------------------------------

TEST(LimitedDequeTest, PushFront)
{
    static constexpr size_t capacity = 5;

    LimitedDeque<uint32_t> deque{capacity};

    for (uint32_t i : views::iota(0u, capacity)) {
        deque.push_front(i);
    }

    EXPECT_THAT(
        deque,
        testing::ElementsAreArray(
            views::iota(0u, capacity)
                | views::reverse
                | ranges::to<std::vector>()));
}

//-------------------------------------------------------------------------

TEST(LimitedDequeTest, CapacityRespected)
{
    static constexpr size_t capacity = 5;

    LimitedDeque<uint32_t> deque{capacity};

    EXPECT_EQ(deque.capacity(), capacity);

    for (uint32_t i : views::iota(0u, capacity * 2)) {
        deque.push_back(i);
    }

    EXPECT_EQ(deque.size(), capacity);
}

//-------------------------------------------------------------------------