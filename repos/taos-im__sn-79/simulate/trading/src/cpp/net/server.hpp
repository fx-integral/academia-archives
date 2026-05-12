/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "json_util.hpp"
#include "net.hpp"

#include <latch>
#include <stop_token>
#include <string>

//-------------------------------------------------------------------------

net::awaitable<void> session(beast::tcp_stream stream, const rapidjson::Value& responsesJson);

//-------------------------------------------------------------------------

net::awaitable<void> listen(
    tcp::endpoint endpoint,
    const rapidjson::Value& responsesJson,
    std::latch& serverReady,
    std::stop_token stopToken);

//-------------------------------------------------------------------------

struct ServerProps
{
    std::string host;
    uint16_t port;
    rapidjson::Document responsesJson;
};

void runServer(ServerProps props, std::latch& serverReady, std::stop_token stopToken);

//-------------------------------------------------------------------------
