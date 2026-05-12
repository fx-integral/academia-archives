/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
// TODO: This suite is getting quite big. Split it somehow?

#include "DistributedProxyAgent.hpp"
#include "MultiBookExchangeAgent.hpp"
#include "Order.hpp"
#include "ParameterStorage.hpp"
#include "PayloadFactory.hpp"
#include "Simulation.hpp"
#include "server.hpp"
#include "util.hpp"

#include <fmt/format.h>
#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <pugixml.hpp>


#include <regex>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <functional>
#include <latch>
#include <memory>
#include <string>
#include <thread>
#include <utility>

#ifndef _WIN32
extern "C" {
    #include <signal.h>
    #include <stdio.h>
}
#endif

//-------------------------------------------------------------------------

using namespace taosim::literals;

using testing::StrEq;
using testing::Values;

namespace fs = std::filesystem;

//-------------------------------------------------------------------------

namespace
{

const auto kTestDataPath = fs::path{__FILE__}.parent_path() / "data";


std::string normalizeOutput(const std::string& input) {
    std::string result = std::regex_replace(input, std::regex(R"((\.\d*?[1-9])0+|\.(0+))"), "$1");
    result = std::regex_replace(result, std::regex(R"(\s{2,})"), " ");
    return result;

}



template<typename... Args>
requires std::constructible_from<PlaceOrderMarketPayload, Args..., BookId>
std::pair<MarketOrder::Ptr, OrderErrorCode> placeMarketOrder(
    MultiBookExchangeAgent& exchange, AgentId agentId, BookId bookId, Args&&... args)
{
    const auto payload =
        MessagePayload::create<PlaceOrderMarketPayload>(std::forward<Args>(args)..., bookId);
    const auto ec = exchange.clearingManager().handleOrder(
        taosim::exchange::MarketOrderDesc{
            .agentId = agentId,
            .payload = payload
        });
    auto marketOrderPtr = exchange.books()[bookId]->placeMarketOrder(
        payload->direction,
        Timestamp{},
        payload->volume,
        payload->leverage,
        OrderClientContext{agentId});
    return {marketOrderPtr, ec};
}

template<typename... Args>
requires std::constructible_from<PlaceOrderLimitPayload, Args..., BookId>
std::pair<LimitOrder::Ptr, OrderErrorCode> placeLimitOrder(
    MultiBookExchangeAgent& exchange, AgentId agentId, BookId bookId, Args&&... args)
{
    const auto payload =
        MessagePayload::create<PlaceOrderLimitPayload>(std::forward<Args>(args)..., bookId);
    const auto ec = exchange.clearingManager().handleOrder(
        taosim::exchange::LimitOrderDesc{
            .agentId = agentId,
            .payload = payload
        });
    auto limitOrderPtr = exchange.books()[bookId]->placeLimitOrder(
        payload->direction,
        Timestamp{},
        payload->volume,
        payload->price,
        payload->leverage,
        OrderClientContext{agentId});
    return {limitOrderPtr, ec};
}

template<typename OrderType, typename... SubArgs>
requires(
    (std::same_as<OrderType, MarketOrder> &&
     std::constructible_from<PlaceOrderMarketPayload, SubArgs..., BookId>) ||
    (std::same_as<OrderType, LimitOrder> &&
     std::constructible_from<PlaceOrderLimitPayload, SubArgs..., BookId>))
void sendOrder(
    MultiBookExchangeAgent* exchange, AgentId agentId, BookId bookId, SubArgs&&... subArgs)
{
    if constexpr (std::same_as<OrderType, MarketOrder>) {
        exchange->receiveMessage(std::make_shared<Message>(
            Timestamp{},
            Timestamp{},
            "foo",
            exchange->name(),
            "DISTRIBUTED_PLACE_ORDER_MARKET",
            std::make_shared<DistributedAgentResponsePayload>(
                agentId,
                MessagePayload::create<PlaceOrderMarketPayload>(
                    std::forward<SubArgs>(subArgs)..., bookId))));
    }
    else {
        exchange->receiveMessage(std::make_shared<Message>(
            Timestamp{},
            Timestamp{},
            "foo",
            exchange->name(),
            "DISTRIBUTED_PLACE_ORDER_LIMIT",
            std::make_shared<DistributedAgentResponsePayload>(
                agentId,
                MessagePayload::create<PlaceOrderLimitPayload>(
                    std::forward<SubArgs>(subArgs)..., bookId))));
    }
}

class MultiBookExchangeAgentTestFixture
    : public testing::TestWithParam<std::pair<Timestamp, fs::path>>
{
protected:
    void SetUp() override
    {
        const auto& [kStepSize, kConfigPath] = GetParam();
        nodes = taosim::util::parseSimulationFile(
            kConfigPath.string().starts_with(fmt::format("{}/", kTestDataPath.c_str()))
                ? kConfigPath
                : kTestDataPath / kConfigPath);
        auto params = std::make_shared<ParameterStorage>();
        params->set("step", std::to_string(kStepSize));
        simulation = std::make_unique<Simulation>(params);
        simulation->configure(nodes.simulation);
        exchange = std::make_unique<MultiBookExchangeAgent>(simulation.get());
        exchange->configure(nodes.exchange);
        simulation->setDebug(false);
    }

    taosim::util::Nodes nodes;
    std::unique_ptr<Simulation> simulation;
    std::unique_ptr<MultiBookExchangeAgent> exchange;
};

}  // namespace



TEST_P(MultiBookExchangeAgentTestFixture, MarketSell)
{

    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "SingleAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent{};
    const BookId bookId{};
    auto& account = exchange.accounts()[agent];
    auto book = exchange.books()[bookId];


    placeLimitOrder(exchange, agent, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent, bookId, OrderDirection::SELL, 1_dec, 101_dec);


    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (99 | 1)\n"
              "Quote: 5000 (4901 | 99)\n"));


    placeMarketOrder(exchange, agent, bookId, OrderDirection::SELL, 1_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1\n"
                "bid\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (99 | 1)\n"
              "Quote: 5000 (5000 | 0)\n"));

}

INSTANTIATE_TEST_SUITE_P(
    SingleAgentMarketSell,
    MultiBookExchangeAgentTestFixture,
    Values(std::pair{Timestamp{10}, "SingleAgent.xml"}),
    [](const auto&) { return "SingleAgent"; });

//-------------------------------------------------------------------------


TEST_P(MultiBookExchangeAgentTestFixture, MarketBuy)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "SingleAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent{};
    const BookId bookId{};
    auto& account = exchange.accounts().at(agent);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    placeMarketOrder(exchange, agent, bookId, OrderDirection::BUY, 1_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (4901 | 99)\n"));
}

INSTANTIATE_TEST_SUITE_P(
    SingleAgentMarket,
    MultiBookExchangeAgentTestFixture,
    Values(std::pair{Timestamp{10}, "SingleAgent.xml"}),
    [](const auto&) { return "SingleAgent"; });

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, SingleAgentCancel)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent{};
    const BookId bookId{};
    auto& account = exchange.accounts().at(agent);
    auto book = exchange.books()[bookId];

    [[maybe_unused]] const auto [o1, e1] =
        placeLimitOrder(exchange, agent, bookId, OrderDirection::BUY, 2_dec, 99_dec);
    [[maybe_unused]] const auto [o2, e2] =
        placeLimitOrder(exchange, agent, bookId, OrderDirection::BUY, 5_dec, DEC(99.5));
    [[maybe_unused]] const auto [o3, e3] =
        placeLimitOrder(exchange, agent, bookId, OrderDirection::SELL, 3_dec, 101_dec);
    [[maybe_unused]] const auto [o4, e4] =
        placeLimitOrder(exchange, agent, bookId, OrderDirection::SELL, 4_dec, 102_dec);

    book->cancelOrderOpt(o1->id());

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq(normalizeOutput("ask,101,3,102,4\n"
              "bid,99.5,5\n")));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (93 | 7)\n"
              "Quote: 5000 (4502.5 | 497.5)\n"));

    book->cancelOrderOpt(o3->id(), DEC(1.5));

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1.5,102,4\n"
              "bid,99.5,5\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (94.5 | 5.5)\n"
              "Quote: 5000 (4502.5 | 497.5)\n"));

    book->cancelOrderOpt(o2->id(), DEC(4.5));

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1.5,102,4\n"
              "bid,99.5,0.5\n"));

    book->cancelOrderOpt(o3->id(), DEC(2.5));  // Note that 2.5 > 1.5.

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,102,4\n"
              "bid,99.5,0.5\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentLimitsMarketSell)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (5000 | 0)\n"));

    placeMarketOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 101 (100 | 1)\n"
              "Quote: 4901 (4901 | 0)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 99 (99 | 0)\n"
              "Quote: 5099 (5099 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentLimitsMarketBuy)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 99 (99 | 0)\n"
              "Quote: 5101 (5002 | 99)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 101 (101 | 0)\n"
              "Quote: 4899 (4899 | 0)\n"));
}


//-------------------------------------------------------------------------



TEST(MultiBookExchangeAgentTest, MultiAgentLimitsMarketBuyExceedingBookCapacity)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 99 (99 | 0)\n"
              "Quote: 5101 (5002 | 99)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 101 (101 | 0)\n"
              "Quote: 4899 (4899 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentLimitsMarketSellExceedingBookCapacity)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    placeMarketOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 101 (100 | 1)\n"
              "Quote: 4901 (4901 | 0)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 99 (99 | 0)\n"
              "Quote: 5099 (5099 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentLimitsMarketBuyFractional)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 99_dec);
    placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 101_dec);

    placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, DEC(0.5));

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,0.5\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 99.5 (99 | 0.5)\n"
              "Quote: 5050.5 (4951.5 | 99)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100.5 (100.5 | 0)\n"
              "Quote: 4949.5 (4949.5 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentCancel)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    [[maybe_unused]] auto [limitBuy, e1] =
        placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 99_dec);
    [[maybe_unused]] auto [limitSell, e2] =
        placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 101_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,2\n"
              "bid,99,2\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (4802 | 198)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100 (98 | 2)\n"
              "Quote: 5000 (5000 | 0)\n"));

    book->cancelOrderOpt(limitBuy->id());

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,2\n"
              "bid\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (5000 | 0)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100 (98 | 2)\n"
              "Quote: 5000 (5000 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentCancelNonExistent)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agent0 = 0, agent1 = 1;
    const BookId bookId{};
    auto& account0 = exchange.accounts().at(agent0);
    auto& account1 = exchange.accounts().at(agent1);
    auto book = exchange.books()[bookId];

    [[maybe_unused]] auto [limitBuy, e1] =
        placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 99_dec);
    [[maybe_unused]] auto [limitSell, e2] =
        placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 101_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,2\n"
              "bid,99,2\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (4802 | 198)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100 (98 | 2)\n"
              "Quote: 5000 (5000 | 0)\n"));

    book->cancelOrderOpt(2);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
        StrEq("ask,101,2\n"
              "bid,99,2\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account0)),
        StrEq("Book 0\n"
              "Base: 100 (100 | 0)\n"
              "Quote: 5000 (4802 | 198)\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account1)),
        StrEq("Book 0\n"
              "Base: 100 (98 | 2)\n"
              "Quote: 5000 (5000 | 0)\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentCancelMultiple)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgentTwoBooks.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId agentId{};
    const BookId bookId0 = 0, bookId1 = 1;
    auto& account = exchange.accounts().at(agentId);
    auto book0 = exchange.books()[bookId0];
    auto book1 = exchange.books()[bookId1];

    [[maybe_unused]] const auto [o1, e1] =
        placeLimitOrder(exchange, agentId, bookId0, OrderDirection::BUY, 1_dec, 99_dec);
    [[maybe_unused]] const auto [o2, e2] =
        placeLimitOrder(exchange, agentId, bookId0, OrderDirection::SELL, 1_dec, 101_dec);
    [[maybe_unused]] const auto [o3, e3] =
        placeLimitOrder(exchange, agentId, bookId1, OrderDirection::BUY, 1_dec, 99_dec);
    [[maybe_unused]] const auto [o4, e4] =
        placeLimitOrder(exchange, agentId, bookId1, OrderDirection::SELL, 1_dec, 101_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book0->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book1->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid,99,1\n"));
    EXPECT_THAT(
        normalizeOutput(fmt::format("{}", account)),
        StrEq("Book 0\n"
              "Base: 100 (99 | 1)\n"
              "Quote: 5000 (4901 | 99)\n"
              "Book 1\n"
              "Base: 100 (99 | 1)\n"
              "Quote: 5000 (4901 | 99)\n"));

    book0->cancelOrderOpt(o1->id(), 1_dec);
    book0->cancelOrderOpt(o2->id(), 1_dec);
    book1->cancelOrderOpt(o3->id(), 1_dec);

    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book0->printCSV(); })),
        StrEq("ask\n"
              "bid\n"));
    EXPECT_THAT(
        normalizeOutput(taosim::util::captureOutput([&] { book1->printCSV(); })),
        StrEq("ask,101,1\n"
              "bid\n"));
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentMoreFullBookWithCancels)
{
    // Configuration.
    static constexpr Timestamp kStepSize = 10;

    [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgentThreeBooks.xml");

    auto params = std::make_shared<ParameterStorage>();
    params->set("step", std::to_string(kStepSize));
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);
    MultiBookExchangeAgent exchange{&simulation};
    exchange.configure(exchangeNode);

    // Actual test logic.
    const AgentId kAgent0 = 0, kAgent1 = 1;
    const BookId kBookId0 = 0, kBookId1 = 1, kBookId2 = 2;
    auto book0 = exchange.books()[kBookId0];
    auto book1 = exchange.books()[kBookId1];
    auto book2 = exchange.books()[kBookId2];

    const auto kTestName = testing::UnitTest::GetInstance()->current_test_info()->name();

    const rapidjson::Document kAgent0OrderPlacementResponsesJson2 =
        taosim::json::loadJson(kTestDataPath / fmt::format("{}.orders0.json", kTestName));
    const rapidjson::Document kAgent1OrderPlacementResponsesJson2 =
        taosim::json::loadJson(kTestDataPath / fmt::format("{}.orders1.json", kTestName));
    const rapidjson::Document kCancelResponsesJson2 =
        taosim::json::loadJson(kTestDataPath / fmt::format("{}.cancels.json", kTestName));

    auto placeOrders2 = [&](const rapidjson::Value& responsesJson) -> void {
        for (const rapidjson::Value& responseJson : responsesJson["responses"].GetArray()) {
            const auto genericPayload = PayloadFactory::createFromJsonMessage(responseJson);
            auto type = std::string_view{responseJson["type"].GetString()};
            if (type == "PLACE_ORDER_MARKET") {
                const AgentId agentId = responseJson["agentId"].GetInt();
                const auto payload = std::dynamic_pointer_cast<PlaceOrderMarketPayload>(genericPayload);
                placeMarketOrder(
                    exchange,
                    agentId,
                    //payload->bookId.value(),
                    payload->bookId,
                    payload->direction,
                    payload->volume,
                    payload->leverage);
            }
            else if (type == "PLACE_ORDER_LIMIT") {
                const AgentId agentId = responseJson["agentId"].GetInt();
                const auto payload = std::dynamic_pointer_cast<PlaceOrderLimitPayload>(genericPayload);
                placeLimitOrder(
                    exchange,
                    agentId,
                    //payload->bookId.value(),
                    payload->bookId,
                    payload->direction,
                    payload->volume,
                    payload->price,
                    payload->leverage);
            }
            else if (type == "CANCEL_ORDERS") {
                const auto payload = std::dynamic_pointer_cast<CancelOrdersPayload>(genericPayload);
                auto book = exchange.books()[payload->bookId];
                for (const auto& cancellation : payload->cancellations) {
                    book->cancelOrderOpt(cancellation.id, cancellation.volume);
                }
            }
        }
        
    };

    placeOrders2(kAgent0OrderPlacementResponsesJson2);
    placeOrders2(kAgent1OrderPlacementResponsesJson2);
    placeOrders2(kCancelResponsesJson2);
}

//-------------------------------------------------------------------------

TEST(MultiBookExchangeAgentTest, MultiAgentMultipleOrdersTradeReplay)
{
    // Configuration.
    [[maybe_unused]] const auto [doc, simulationNode, _] =
        taosim::util::parseSimulationFile(kTestDataPath / "MultiAgentThreeBooksReplay.xml");

    auto params = std::make_shared<ParameterStorage>();
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.setDebug(false);

    const auto kTestName = testing::UnitTest::GetInstance()->current_test_info()->name();

    // Run a proxy server.
    std::latch serverReady{1};
    auto proxy = std::jthread{[&](std::stop_token stopToken) -> void {
        try {
            const auto& distributedProxyAgentNode = 
                simulationNode.child("Agents").child("DistributedProxyAgent");
            ServerProps props{
                .host = distributedProxyAgentNode.attribute("host").as_string(),
                .port =
                    static_cast<uint16_t>(distributedProxyAgentNode.attribute("port").as_uint()),
                .responsesJson =
                    taosim::json::loadJson(kTestDataPath / fmt::format("{}.json", kTestName))};
            runServer(std::move(props), serverReady, stopToken);
        }
        catch (const std::exception& e) {
            std::cerr << "Server error: " << e.what() << "\n";
        }
    }};
    proxy.detach();

    serverReady.wait();
    simulation.simulate();
}

//-------------------------------------------------------------------------

class DropoutFixture : public testing::TestWithParam<std::string>
{
protected:
    virtual void SetUp() override
    {
        dataFilePrefix = GetParam();
    }

    ParamType dataFilePrefix;
};

TEST_P(DropoutFixture, BookStateMatch)
{
    // Configuration.
    [[maybe_unused]] const auto [doc, simulationNode, _] =
        taosim::util::parseSimulationFile(kTestDataPath / "BookStateMatch.xml");

    auto params = std::make_shared<ParameterStorage>();
    Simulation simulation{params};
    simulation.configure(simulationNode);
    simulation.exchange()->retainRecord(true);
    simulation.exchange()->setParallel(false);
    simulation.setDebug(false);
    
    for (auto& agent : simulation.agents()) {
        if (agent->name() == "DISTRIBUTED_PROXY_AGENT") {
            std::bit_cast<DistributedProxyAgent*>(agent.get())->setTestMode(true);
            break;
        }
    }

    // Run a proxy server.
    std::latch serverReady{1};
    auto proxy = std::jthread{[&](std::stop_token stopToken) -> void {
        try {
            const auto& distributedProxyAgentNode =
                simulationNode.child("Agents").child("DistributedProxyAgent");
            ServerProps props{
                .host = distributedProxyAgentNode.attribute("host").as_string(),
                .port =
                    static_cast<uint16_t>(distributedProxyAgentNode.attribute("port").as_uint()),
                .responsesJson =
                    taosim::json::loadJson(kTestDataPath / fmt::format("{}.responses.json", dataFilePrefix))};
            runServer(std::move(props), serverReady, stopToken);
        }
        catch (const std::exception& e) {
            std::cerr << "Server error: " << e.what() << "\n";
        }
    }};
    proxy.detach();

    serverReady.wait();
    simulation.simulate();

    auto state = [&] -> rapidjson::Document {
        rapidjson::Document json;
        simulation.exchange()->jsonSerialize(json);
        json.RemoveMember("accounts");
        return json;
    }();

    static constexpr float epsilon = 1e-4;

    auto expectStateMatch = [](const rapidjson::Value& lhs, const rapidjson::Value& rhs) -> void {
        const rapidjson::Value& booksLhs = lhs["books"].GetArray();
        const rapidjson::Value& booksRhs = rhs["books"].GetArray();
        EXPECT_EQ(booksLhs.Size(), booksRhs.Size());
        const size_t bookCount = booksLhs.Size();

        auto expectSidesMatch = [&](BookId bookId, const char* side) -> void {
            const rapidjson::Value& lhs = booksLhs[bookId][side].GetArray();
            const rapidjson::Value& rhs = booksRhs[bookId][side].GetArray();
            EXPECT_EQ(lhs.Size(), rhs.Size());
            const size_t numLevels = rhs.Size();

            auto extraInfo = [&](int i, const rapidjson::Value& lhs, const rapidjson::Value& rhs) {
                return fmt::format(
                    "\nOrder at index {} in book {} is \n\n{}\nshould be\n\n{}",
                    i,
                    bookId,
                    taosim::json::json2str(lhs, {.indent = taosim::json::IndentOptions{}}),
                    taosim::json::json2str(rhs, {.indent = taosim::json::IndentOptions{}}));
            };

            for (size_t i = 0; i < numLevels; ++i) {
                EXPECT_EQ(lhs[i]["orders"].Size(), 1)
                    << fmt::format("\n{}", taosim::json::json2str(lhs[i], {.indent = taosim::json::IndentOptions{}}));
                const rapidjson::Value& orderLhs = lhs[i]["orders"][0];
                const rapidjson::Value& orderRhs = rhs[i]["orders"][0];
                ASSERT_EQ(orderLhs["direction"].GetUint(), orderRhs["direction"].GetUint())
                    << extraInfo(i, orderLhs, orderRhs);
                ASSERT_EQ(orderLhs["orderId"].GetUint(), orderRhs["orderId"].GetUint())
                    << extraInfo(i, orderLhs, orderRhs);
                ASSERT_EQ(orderLhs["timestamp"].GetUint64(), orderRhs["timestamp"].GetUint64())
                    << extraInfo(i, orderLhs, orderRhs);
                ASSERT_EQ(taosim::json::getDecimal(orderLhs["volume"]), taosim::json::getDecimal(orderRhs["volume"]))
                    << extraInfo(i, orderLhs, orderRhs);
                ASSERT_EQ(taosim::json::getDecimal(lhs[i]["price"]), taosim::json::getDecimal(rhs[i]["price"]))
                    << extraInfo(i, orderLhs, orderRhs);
                ASSERT_EQ(taosim::json::getDecimal(lhs[i]["volume"]), taosim::json::getDecimal(rhs[i]["volume"]))
                    << extraInfo(i, orderLhs, orderRhs);
            }
        };

        auto expectRecordsMatch = [&](BookId bookId) -> void {
            const rapidjson::Value& lhs = booksLhs[bookId]["record"].GetArray();
            const rapidjson::Value& rhs = booksRhs[bookId]["record"].GetArray();
            EXPECT_EQ(lhs.Size(), rhs.Size());
            const size_t recordSize = rhs.Size();

            auto extraInfo = [&](int i, const rapidjson::Value& lhs, const rapidjson::Value& rhs) {
                return fmt::format(
                    "Entry at index {} in book {} is \n\n{}\nshould be\n\n{}",
                    i,
                    bookId,
                    taosim::json::json2str(lhs, {.indent = taosim::json::IndentOptions{}}),
                    taosim::json::json2str(rhs, {.indent = taosim::json::IndentOptions{}}));
            };

            for (size_t i = 0; i < recordSize; ++i) {
                const rapidjson::Value& entryLhs = lhs[i];
                const rapidjson::Value& entryRhs = rhs[i];
                ASSERT_EQ(entryLhs["agentId"].GetUint(), entryRhs["agentId"].GetUint())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(entryLhs["clientOrderId"].IsNull(), entryRhs["clientOrderId"].IsNull())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(entryLhs["direction"].GetUint(), entryRhs["direction"].GetUint())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_STREQ(entryLhs["event"].GetString(), entryRhs["event"].GetString())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(entryLhs["orderId"].GetUint(), entryRhs["orderId"].GetUint())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(taosim::json::getDecimal(entryLhs["price"]), taosim::json::getDecimal(entryRhs["price"]))
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(entryLhs["timestamp"].GetUint64(), entryRhs["timestamp"].GetUint64())
                    << extraInfo(i, entryLhs, entryRhs);
                ASSERT_EQ(taosim::json::getDecimal(entryLhs["volume"]), taosim::json::getDecimal(entryRhs["volume"]))
                    << extraInfo(i, entryLhs, entryRhs);          
            }
        };

        for (BookId bookId{}; bookId < bookCount; ++bookId) {
            expectSidesMatch(bookId, "ask");
            expectSidesMatch(bookId, "bid");
            expectRecordsMatch(bookId);
        }
    };

    expectStateMatch(
        state,
        taosim::json::loadJson(kTestDataPath / fmt::format("{}.state.json", dataFilePrefix)));
}

INSTANTIATE_TEST_SUITE_P(
    DropoutSuite,
    DropoutFixture,
    Values("dropout"));



//-------------------------------------------------------------------------



#ifndef _WIN32

extern "C" void segfault_handler(int sig)
{
    printf("Segmentation fault\n");
    exit(1);
}

int main(int argc, char** argv)
{
    testing::InitGoogleTest(&argc, argv);
    signal(SIGSEGV, segfault_handler);
    return RUN_ALL_TESTS();
}

#endif

//-------------------------------------------------------------------------
