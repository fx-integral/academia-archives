/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#include "net.hpp"

//------------------------------------------------------------------------

net::awaitable<void> timeout(std::chrono::steady_clock::duration duration)
{
    net::steady_timer timer{co_await this_coro::executor};
    timer.expires_after(duration);
    co_await timer.async_wait(use_nothrow_awaitable);
}

//------------------------------------------------------------------------

net::awaitable<void> timeout(int64_t duration)
{
    net::steady_timer timer{co_await this_coro::executor};
    timer.expires_after(std::chrono::seconds{duration});
    co_await timer.async_wait(use_nothrow_awaitable);
}

//------------------------------------------------------------------------
