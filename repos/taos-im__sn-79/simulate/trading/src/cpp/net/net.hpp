/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <boost/asio/awaitable.hpp>
#include <boost/asio/co_spawn.hpp>
#include <boost/asio/detached.hpp>
#include <boost/asio/as_tuple.hpp>
#include <boost/asio/experimental/awaitable_operators.hpp>
#include <boost/asio/use_awaitable.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>

#include <chrono>

//-------------------------------------------------------------------------

namespace net = boost::asio;
using net::use_awaitable;
using tcp = net::ip::tcp;
namespace ip = net::ip;
namespace this_coro = net::this_coro;
using namespace net::experimental::awaitable_operators;

namespace beast = boost::beast;
namespace http = beast::http;

using namespace std::literals::chrono_literals;
using std::chrono::steady_clock;

inline constexpr auto use_nothrow_awaitable = net::as_tuple(use_awaitable);

//-------------------------------------------------------------------------

net::awaitable<void> timeout(std::chrono::steady_clock::duration duration);
net::awaitable<void> timeout(int64_t duration);

//-------------------------------------------------------------------------
