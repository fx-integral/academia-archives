/*
 * SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
 * SPDX-License-Identifier: MIT
 */
// // TODO: This suite is getting quite big. Split it somehow?

// #include "DistributedProxyAgent.hpp"
// #include "MultiBookExchangeAgent.hpp"
// #include "Order.hpp"
// #include "ParameterStorage.hpp"
// #include "PayloadFactory.hpp"
// #include "Simulation.hpp"
// #include "server.hpp"
// #include "util.hpp"
// #include "ClearingManager.hpp"

// #include <fmt/format.h>
// #include <gmock/gmock.h>
// #include <gtest/gtest.h>
// #include <pugixml.hpp>


// #include <regex>
// #include <cassert>
// #include <filesystem>
// #include <fstream>
// #include <functional>
// #include <latch>
// #include <memory>
// #include <string>
// #include <thread>
// #include <utility>

// #ifndef _WIN32
// extern "C" {
//     #include <signal.h>
//     #include <stdio.h>
// }
// #endif

// //-------------------------------------------------------------------------

// using namespace taosim::literals;
// using namespace taosim::exchange;

// using testing::StrEq;
// using testing::Values;

// namespace fs = std::filesystem;


// //-------------------------------------------------------------------------

// namespace
// {

// const auto kTestDataPath = fs::path{__FILE__}.parent_path() / "data";


// std::string normalizeOutput(const std::string& input) {
//     std::string result = std::regex_replace(input, std::regex(R"((\.\d*?[1-9])0+|\.(0+))"), "$1");
//     result = std::regex_replace(result, std::regex(R"(\s{2,})"), " ");
//     return result;

// }

// void printMarginMap(const ClearingManager::MarginCallContainer& marginBuy, const ClearingManager::MarginCallContainer& marginSell) {

//     // Get all book IDs from both maps
//     std::set<BookId> allBooks;
//     for (const auto& [bookId, _] : marginBuy) allBooks.insert(bookId);
//     for (const auto& [bookId, _] : marginSell) allBooks.insert(bookId);

//     fmt::println("=======================================");
//     if (allBooks.empty()){
//         fmt::println("----------- No Active Margin order ------------");
//     }
//     for (const auto& bookId : allBooks) {
//         fmt::println("BookID: {}", bookId);

//         if (marginSell.find(bookId) != marginSell.end()) {
//             fmt::println("  ___ Short Selling _____________");
//             for (const auto& [decimalValue, orderList] : marginSell.at(bookId)) {
//                 fmt::println("        PriceLevel: {}", decimalValue);
//                 for (const auto& [orderId, agentId] : orderList) {
//                     fmt::println("            OrderID: {} ,  AgentID: {}", orderId, agentId);
//                 }
//             }
//         } else {
//             fmt::println("----- No Short Selling Price Levels -----");
//         }

//         if (marginBuy.find(bookId) != marginBuy.end()) {
//             fmt::println("  ___ Margin Buying _____________");
//             for (const auto& [decimalValue, orderList] : marginBuy.at(bookId)) {
//                 fmt::println("        PriceLevel: {}", decimalValue);
//                 for (const auto& [orderId, agentId] : orderList) {
//                     fmt::println("            OrderID: {} ,  AgentID: {}", orderId, agentId);
//                 }
//             }
//         } else {
//             fmt::println("----- No Margin Buying Price Levels -----");
//         }
//     }
//     fmt::println("=======================================");
// }


// template<typename... Args>
// requires std::constructible_from<PlaceOrderMarketPayload, Args..., BookId>
// std::pair<MarketOrder::Ptr, OrderErrorCode> placeMarketOrder(
//     MultiBookExchangeAgent& exchange, AgentId agentId, BookId bookId, Args&&... args)
// {
//     const auto payload =
//         MessagePayload::create<PlaceOrderMarketPayload>(std::forward<Args>(args)..., bookId);
//     const auto ec = exchange.clearingManager().handleOrder(MarketOrderDesc{.agentId = agentId, .payload = payload});
//     auto marketOrderPtr = exchange.books()[bookId]->placeMarketOrder(
//         payload->direction,
//         Timestamp{},
//         payload->volume,
//         payload->leverage,
//         OrderClientContext{agentId});
//     return {marketOrderPtr, ec};
// }

// template<typename... Args>
// requires std::constructible_from<PlaceOrderLimitPayload, Args..., BookId>
// std::pair<LimitOrder::Ptr, OrderErrorCode> placeLimitOrder(
//     MultiBookExchangeAgent& exchange, AgentId agentId, BookId bookId, Args&&... args)
// {
//     const auto payload =
//         MessagePayload::create<PlaceOrderLimitPayload>(std::forward<Args>(args)..., bookId);
//     const auto ec = exchange.clearingManager().handleOrder(LimitOrderDesc{.agentId = agentId, .payload = payload});
//     auto limitOrderPtr = exchange.books()[bookId]->placeLimitOrder(
//         payload->direction,
//         Timestamp{},
//         payload->volume,
//         payload->price,
//         payload->leverage,
//         OrderClientContext{agentId});
//     return {limitOrderPtr, ec};
// }

// template<typename OrderType, typename... SubArgs>
// requires(
//     (std::same_as<OrderType, MarketOrder> &&
//      std::constructible_from<PlaceOrderMarketPayload, SubArgs..., BookId>) ||
//     (std::same_as<OrderType, LimitOrder> &&
//      std::constructible_from<PlaceOrderLimitPayload, SubArgs..., BookId>))
// void sendOrder(
//     MultiBookExchangeAgent* exchange, AgentId agentId, BookId bookId, SubArgs&&... subArgs)
// {
//     if constexpr (std::same_as<OrderType, MarketOrder>) {
//         exchange->receiveMessage(std::make_shared<Message>(
//             Timestamp{},
//             Timestamp{},
//             "foo",
//             exchange->name(),
//             "DISTRIBUTED_PLACE_ORDER_MARKET",
//             std::make_shared<DistributedAgentResponsePayload>(
//                 agentId,
//                 MessagePayload::create<PlaceOrderMarketPayload>(
//                     std::forward<SubArgs>(subArgs)..., bookId))));
//     }
//     else {
//         exchange->receiveMessage(std::make_shared<Message>(
//             Timestamp{},
//             Timestamp{},
//             "foo",
//             exchange->name(),
//             "DISTRIBUTED_PLACE_ORDER_LIMIT",
//             std::make_shared<DistributedAgentResponsePayload>(
//                 agentId,
//                 MessagePayload::create<PlaceOrderLimitPayload>(
//                     std::forward<SubArgs>(subArgs)..., bookId))));
//     }
// }

// class MultiBookExchangeAgentTestFixture
//     : public testing::TestWithParam<std::pair<Timestamp, fs::path>>
// {
// protected:
//     void SetUp() override
//     {
//         const auto& [kStepSize, kConfigPath] = GetParam();
//         nodes = taosim::util::parseSimulationFile(
//             kConfigPath.string().starts_with(fmt::format("{}/", kTestDataPath.c_str()))
//                 ? kConfigPath
//                 : kTestDataPath / kConfigPath);
//         auto params = std::make_shared<ParameterStorage>();
//         params->set("step", std::to_string(kStepSize));
//         simulation = std::make_unique<Simulation>(params);
//         simulation->configure(nodes.simulation);
//         exchange = std::make_unique<MultiBookExchangeAgent>(simulation.get());
//         exchange->configure(nodes.exchange);
//         simulation->setDebug(false);
//     }

//     taosim::util::Nodes nodes;
//     std::unique_ptr<Simulation> simulation;
//     std::unique_ptr<MultiBookExchangeAgent> exchange;
// };

// }  // namespace


// //-------------------------------------------------------------------------


// /*

// TEST(MarginTradingTests, MultiAgentMarginBuy)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = 0, agent1 = 1;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 100_dec, DEC(3.));

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,100,4\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10300 (9900 | 400)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10000 (10000 | 0)\n"));


//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10004 (10004 | 0)\n"
//               "Quote: 9900 (9900 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 9996 (9996 | 0)\n"
//               "Quote: 10400 (10400 | 0)\n"));

// }



// //-------------------------------------------------------------------------


// TEST(MarginTradingTests, MultiAgentMarginTradeBuy)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = 0, agent1 = 1;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 100_dec, DEC(3.));

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,100,4\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10300 (9900 | 400)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10000 (10000 | 0)\n"));

    

//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::SELL, 3_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,100,1\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10003 (10003 | 0)\n"
//               "Quote: 10000 (9900 | 100)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 9997 (9997 | 0)\n"
//               "Quote: 10300 (10300 | 0)\n"));

    
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 3_dec, 150_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,150,3\n"
//               "bid,100,1\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10003 (10000 | 3)\n"
//               "Quote: 10000 (9900 | 100)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 9997 (9997 | 0)\n"
//               "Quote: 10300 (10300 | 0)\n"));

    
//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 3_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,100,1\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10225 (10125 | 100)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 9850 (9850 | 0)\n"));\

    
//     book->cancelOrderOpt(0);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10150 (10150 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 9850 (9850 | 0)\n"));
    
// }


// //-------------------------------------------------------------------------



// TEST(MarginTradingTests, MultiAgentMarginSell)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = 0, agent1 = 1;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 100_dec, DEC(3.));

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,100,4\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10003 (9999 | 4)\n"
//               "Quote: 10000 (10000 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10000 (10000 | 0)\n"));


//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 4_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 9999 (9999 | 0)\n"
//               "Quote: 10400 (10400 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10004 (10004 | 0)\n"
//               "Quote: 9600 (9600 | 0)\n"));


// }



// //-------------------------------------------------------------------------


// TEST(MarginTradingTests, MultiAgentMarginSell2)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = 0, agent1 = 1;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 100_dec, DEC(3.));

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,100,4\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10003 (9999 | 4)\n"
//               "Quote: 10000 (10000 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10000 (10000 | 0)\n"));


//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 3_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,100,1\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (9999 | 1)\n"
//               "Quote: 10300 (10300 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10003 (10003 | 0)\n"
//               "Quote: 9700 (9700 | 0)\n"));

//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 9999 (9999 | 0)\n"
//               "Quote: 10400 (10400 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10004 (10004 | 0)\n"
//               "Quote: 9600 (9600 | 0)\n"));


// }



// //-------------------------------------------------------------------------


// TEST(MarginTradingTests, MultiAgentMarginTradeSell)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = 0, agent1 = 1;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 150_dec, DEC(3.));

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,150,4\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10003 (9999 | 4)\n"
//               "Quote: 10000 (10000 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10000 (10000 | 0)\n"));


//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::BUY, 3_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,150,1\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (9999 | 1)\n"
//               "Quote: 10450 (10450 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10003 (10003 | 0)\n"
//               "Quote: 9550 (9550 | 0)\n"));

    
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 3_dec, 100_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,150,1\n"
//               "bid,100,3\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (9999 | 1)\n"
//               "Quote: 10450 (10150 | 300)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10003 (10003 | 0)\n"
//               "Quote: 9550 (9550 | 0)\n"));


//     placeMarketOrder(exchange, agent1, bookId, OrderDirection::SELL, 3_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,150,1\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000.75 (9999.75 | 1)\n"
//               "Quote: 10150 (10150 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 9850 (9850 | 0)\n"));


//     book->cancelOrderOpt(0);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account0)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 10150 (10150 | 0)\n"));
//     EXPECT_THAT(
//         normalizeOutput(fmt::format("{}", account1)),
//         StrEq("Book 0\n"
//               "Base: 10000 (10000 | 0)\n"
//               "Quote: 9850 (9850 | 0)\n"));
    
// }



// //-------------------------------------------------------------------------


// TEST(MarginTradingTests, MultiAgentMarginCallBuy)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);

    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 5_dec, 80_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,80,5\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 10_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 5_dec, 40_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,80,5,40,5,10,2\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     book->cancelOrderOpt(2);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,40,5,10,2\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
// }


// //-------------------------------------------------------------------------

// TEST(MarginTradingTests, MultiAgentMarginCallSell)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2;
//     const BookId bookId{};
//     auto& account0 = exchange.accounts()[agent0];
//     auto& account1 = exchange.accounts()[agent1];
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 100_dec, DEC(1.));
    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 4_dec, 100_dec);

    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());


//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 5_dec, 110_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,110,5\n"
//               "bid\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 150_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 5_dec, 125_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,110,5,125,5,150,2\n"
//               "bid\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     book->cancelOrderOpt(2);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,125,5,150,2\n"
//               "bid\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
// }



// */



// //-------------------------------------------------------------------------

// /*
// TEST(MarginTradingTests, MultiAgentMarginCallSingleAgent)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
//     const BookId bookId{};
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");
//     exchange.accounts().registerLocal("agent2");

//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 100_dec, DEC(1.));
//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
    

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("#################### Agent {} ###################", agId);
//         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//         fmt::println("{}", balanceString);
//         fmt::println("++++++++++++++++++++++++++++++++++++");
//     }

    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
    
    

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }


//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("#################### Agent {} ###################", agId);
//         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//         fmt::println("{}", balanceString);
//         fmt::println("++++++++++++++++++++++++++++++++++++");
//     }

    

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
    
    
    
//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 150_dec);

//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 4_dec, 150_dec);
    
//     //placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 150_dec);
    
    
    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 150_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 150_dec);
    
    
    
    
    


//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 4_dec, 110_dec);
//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 4_dec, 110_dec);
    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }
//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("#################### Agent {} ###################", agId);
//         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//         fmt::println("{}", balanceString);
//         fmt::println("++++++++++++++++++++++++++++++++++++");
//     }

//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 100_dec);
//     //placeMarketOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec);

//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 150_dec);
    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec, 150_dec);

//     exchange.checkMarginCall();
    
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());


//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }
//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("#################### Agent {} ###################", agId);
//         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//         fmt::println("{}", balanceString);
//         fmt::println("++++++++++++++++++++++++++++++++++++");
//     }
    
    
// }
// */


// //-------------------------------------------------------------------------



// TEST(MarginTradingTests, MultiAgentMarginCall)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
//     const BookId bookId{};
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");
//     exchange.accounts().registerLocal("agent2");

//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 100_dec, DEC(1.));
    
//     // placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
    

//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("========== Agent {} ==========", agId);
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//     //         fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//     //         fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     fmt::println("------------------------------------");
//     // }

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("#################### Agent {} ###################", agId);
//         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//         fmt::println("{}", balanceString);
//         fmt::println("++++++++++++++++++++++++++++++++++++");
//     }

    
//     // EXPECT_THAT(
//     //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//     //     StrEq("ask\n"
//     //           "bid\n"));
    
//     // exchange.checkMarginCall();
//     // printMarginMap(exchange.clearingManager().getMarginBuys(), exchange.clearingManager().getMarginSells());

//     // placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     // //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
//     // placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 4_dec, 100_dec);
    
    

//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("========== Agent {} ==========", agId);
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//     //         fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//     //         fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     fmt::println("------------------------------------");
//     // }


//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("#################### Agent {} ###################", agId);
//     //     std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//     //     fmt::println("{}", balanceString);
//     //     fmt::println("++++++++++++++++++++++++++++++++++++");
//     // }

    

//     // exchange.checkMarginCall();
//     // printMarginMap(exchange.clearingManager().getMarginBuys(), exchange.clearingManager().getMarginSells());

    
    
    
    
    
//     // //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 8_dec, 150_dec);
//     // //placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 10_dec, 150_dec);
//     // //placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 150_dec);
    
    
    
//     // placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 4_dec, 110_dec);
//     // placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 4_dec, 110_dec);
    
    
    
    

    
//     // //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 4_dec, 110_dec);
//     // //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 4_dec, 110_dec);

//     // printMarginMap(exchange.clearingManager().getMarginBuys(), exchange.clearingManager().getMarginSells());
    
//     // EXPECT_THAT(
//     //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//     //     StrEq("ask\n"
//     //           "bid\n"));
    
//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("========== Agent {} ==========", agId);
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//     //         fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//     //         fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     fmt::println("------------------------------------");
//     // }
//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("#################### Agent {} ###################", agId);
//     //     std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//     //     fmt::println("{}", balanceString);
//     //     fmt::println("++++++++++++++++++++++++++++++++++++");
//     // }

//     // //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 100_dec);
//     // //placeMarketOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec);

//     // placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 40_dec);

//     // //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 5_dec, 110_dec);
    

    

//     // exchange.checkMarginCall();
    
//     // printMarginMap(exchange.clearingManager().getMarginBuys(), exchange.clearingManager().getMarginSells());


//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("========== Agent {} ==========", agId);
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//     //         fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//     //         fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
//     //     }
//     //     fmt::println("------------------------------------");
//     // }
//     // for (AgentId agId = -1; agId > -4; agId--){
//     //     fmt::println("#################### Agent {} ###################", agId);
//     //     std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
//     //     fmt::println("{}", balanceString);
//     //     fmt::println("++++++++++++++++++++++++++++++++++++");
//     // }
    
    
// }




// /*

// TEST(MarginTradingTests, MultiAgentMarginCall)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
//     const BookId bookId{};
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");
//     exchange.accounts().registerLocal("agent2");

//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 100_dec, DEC(1.));

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
    

//     //placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, DEC(4.5), 110_dec);
//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 3_dec, 110_dec, DEC(.5));

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 5_dec, 110_dec);
    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid,110,5\n"));
    
//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

    
//     exchange.checkMarginCall();
    
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());
    
    
// }
// */

// //-------------------------------------------------------------------------

// /*
// TEST(MarginTradingTests, MultiAgentMarginCall)
// {
//     // Configuration.
//     static constexpr Timestamp kStepSize = 10;

//     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
//         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

//     auto params = std::make_shared<ParameterStorage>();
//     params->set("step", std::to_string(kStepSize));
//     Simulation simulation{params};
//     simulation.configure(simulationNode);
//     simulation.setDebug(false);
//     MultiBookExchangeAgent exchange{&simulation};
//     exchange.configure(exchangeNode);

//     // Actual test logic.
//     const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
//     const BookId bookId{};
//     auto book = exchange.books()[bookId];
    
//     // need to register the agents
//     exchange.accounts().registerLocal("agent0");
//     exchange.accounts().registerLocal("agent1");
//     exchange.accounts().registerLocal("agent2");


//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 4_dec, 100_dec);
//     //placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask\n"
//               "bid\n"));
    
//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

//     placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 100_dec, DEC(1.));
//     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 4_dec, 100_dec);

//     //placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, DEC(4.5), 110_dec);
//     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 3_dec, 110_dec, DEC(.5));

//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 5_dec, 110_dec);
    
//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,110,5\n"
//               "bid\n"));
    
//     for (AgentId agId = -1; agId > -4; agId--){
//         fmt::println("========== Agent {} ==========", agId);
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
//             fmt::println("*** Base  loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
//             fmt::println("*** Qoute loanId:{}  vol:{} amount:{}", loan_id, loan.volume, loan.amount);
//         }
//         fmt::println("------------------------------------");
//     }

    
//     exchange.checkMarginCall();
    
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());
    
     

//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 150_dec);
//     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 5_dec, 125_dec);

//     EXPECT_THAT(
//         normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
//         StrEq("ask,110,5,125,5,150,2\n"
//               "bid\n"));

//     exchange.checkMarginCall();
//     printMarginMap(exchange.getMarginBuys(), exchange.getMarginSells());

    
    
    
    
// }
// */











// // TEST_P(MarginTradingTests, MarketSell)
// // {


// //     //Configuration.
// //     static constexpr Timestamp kStepSize = 10;

// //     [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
// //         taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

// //     auto params = std::make_shared<ParameterStorage>();
// //     params->set("step", std::to_string(kStepSize));
// //     Simulation simulation{params};
// //     simulation.configure(simulationNode);
// //     simulation.setDebug(false);
// //     MultiBookExchangeAgent exchange{&simulation};
// //     exchange.configure(exchangeNode);
// //     // m_clearingManager = std::make_unique<taosim::exchange::ClearingManager>(
// //     //         this, taosim::exchange::FeePolicyFactory::createFromXML(node.child("FeePolicy")));

// //     // Actual test logic.
// //     const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
// //     const BookId bookId{};
// //     auto book = exchange.books()[bookId];    
    
// //     // need to register the agents
// //     exchange.accounts().registerLocal("agent0");
// //     exchange.accounts().registerLocal("agent1");
// //     exchange.accounts().registerLocal("agent2");

// //     auto& account = exchange.accounts()[agent0][bookId];




// //     //===========================================
// //     placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 7_dec, 90_dec, 1_dec);


// //     fmt::println("\n");
// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("========== Agent {} ==========", agId);
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //             fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //             fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         fmt::println("------------------------------------");
// //     }

// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("#################### Agent {} ###################", agId);
// //         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //         fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //         fmt::println("++++++++++++++++++++++++++++++++++++");
// //     }






// //     //===========================================

// //     placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 7_dec, 90_dec, 1_dec);
    
    
// //     fmt::println("\n");

// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("========== Agent {} ==========", agId);
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //             fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //             fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         fmt::println("------------------------------------");
// //     }

// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("#################### Agent {} ###################", agId);
// //         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //         fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //         fmt::println("++++++++++++++++++++++++++++++++++++");
// //     }


// //     // EXPECT_THAT(
// //     //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //     //     StrEq("ask,101,1\n"
// //     //         "bid,90,2\n"));

    
// //     //===========================================
// //     placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 7_dec, 110_dec);
// //     placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 7_dec, 110_dec);
    


// //     fmt::println("\n");
// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("========== Agent {} ==========", agId);
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //             fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //             fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         fmt::println("------------------------------------");
// //     }

// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("#################### Agent {} ###################", agId);
// //         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //         fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //         fmt::println("++++++++++++++++++++++++++++++++++++");
// //     }

    

// //     // // EXPECT_THAT(
// //     // //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //     // //     StrEq("ask,101,1\n"
// //     // //         "bid\n"));

    
// //     //===========================================
// //     placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 10_dec, 110_dec);
// //     placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 10_dec, 110_dec);
    
            

    
// //     //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec);

// //     // EXPECT_THAT(
// //     //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //     //     StrEq("ask,101,1\n"
// //     //         "bid\n"));

// //     fmt::println("\n");
// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("========== Agent {} ==========", agId);
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //             fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //             fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //         }
// //         fmt::println("------------------------------------");
// //     }

// //     for (AgentId agId = -1; agId > -4; agId--){
// //         fmt::println("#################### Agent {} ###################", agId);
// //         std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //         fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //         fmt::println("++++++++++++++++++++++++++++++++++++");
// //     }
// // }

// // INSTANTIATE_TEST_SUITE_P(
// //     SingleAgentMarketSell,
// //     MarginTradingTests,
// //     Values(std::pair{Timestamp{10}, "SingleAgent.xml"}),
// //     [](const auto&) { return "SingleAgent"; });





















// //-------------------------------------------------------------------------



// // TEST_P(MultiBookExchangeAgentTestFixture, MarketSell)
// // {

// //     for (int condition = 1; condition <= 8; condition ++){

// //         //Configuration.
// //         static constexpr Timestamp kStepSize = 10;

// //         [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
// //             taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

// //         auto params = std::make_shared<ParameterStorage>();
// //         params->set("step", std::to_string(kStepSize));
// //         Simulation simulation{params};
// //         simulation.configure(simulationNode);
// //         simulation.setDebug(false);
// //         MultiBookExchangeAgent exchange{&simulation};
// //         exchange.configure(exchangeNode);
// //         // m_clearingManager = std::make_unique<taosim::exchange::ClearingManager>(
// //         //         this, taosim::exchange::FeePolicyFactory::createFromXML(node.child("FeePolicy")));

// //         // Actual test logic.
// //         const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
// //         const BookId bookId{};
// //         auto book = exchange.books()[bookId];    
        
// //         // need to register the agents
// //         exchange.accounts().registerLocal("agent0");
// //         exchange.accounts().registerLocal("agent1");
// //         exchange.accounts().registerLocal("agent2");

// //         auto& account = exchange.accounts()[agent0][bookId];

    

// //         fmt::println("#################################################################");
// //         fmt::println("######################### condition: {} ###########################", condition);


// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec, 90_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 90_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec, 90_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 90_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //         }
        


// //         fmt::println("\n");
// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }






// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //         }

        
// //         fmt::println("\n");

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }


// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid,90,2\n"));


// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec, 90_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 90_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 1_dec, 90_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 1_dec, 90_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 break;
// //         }
        


// //         fmt::println("\n");
// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }


// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid\n"));

        
// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 1_dec, 110_dec);
// //                 break;
// //         }

        
// //         //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec);

// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid\n"));

// //         fmt::println("\n");
// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}  | inventory: {}", balanceString, exchange.accounts()[agId][bookId].getInventory());
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }

        
// //         fmt::println("\n###############################################################################################");
// //         fmt::println("################################################################################################\n\n");
// //     }

// // }

// // INSTANTIATE_TEST_SUITE_P(
// //     SingleAgentMarketSell,
// //     MultiBookExchangeAgentTestFixture,
// //     Values(std::pair{Timestamp{10}, "SingleAgent.xml"}),
// //     [](const auto&) { return "SingleAgent"; });

// // //-------------------------------------------------------------------------














// // //-------------------------------------------------------------------------



// // TEST_P(MultiBookExchangeAgentTestFixture, MarketSell)
// // {

// //     for (int condition = 1; condition <= 8; condition ++){

// //         //Configuration.
// //         static constexpr Timestamp kStepSize = 10;

// //         [[maybe_unused]] const auto [doc, simulationNode, exchangeNode] =
// //             taosim::util::parseSimulationFile(kTestDataPath / "MultiAgent.xml");

// //         auto params = std::make_shared<ParameterStorage>();
// //         params->set("step", std::to_string(kStepSize));
// //         Simulation simulation{params};
// //         simulation.configure(simulationNode);
// //         simulation.setDebug(false);
// //         MultiBookExchangeAgent exchange{&simulation};
// //         exchange.configure(exchangeNode);
// //         // m_clearingManager = std::make_unique<taosim::exchange::ClearingManager>(
// //         //         this, taosim::exchange::FeePolicyFactory::createFromXML(node.child("FeePolicy")));

// //         // Actual test logic.
// //         const AgentId agent0 = -1, agent1 = -2, agent2 = -3;
// //         const BookId bookId{};
// //         auto book = exchange.books()[bookId];    
        
// //         // need to register the agents
// //         exchange.accounts().registerLocal("agent0");
// //         exchange.accounts().registerLocal("agent1");
// //         exchange.accounts().registerLocal("agent2");

// //         auto& account = exchange.accounts()[agent0][bookId];

    

// //         fmt::println("#################################################################");
// //         fmt::println("######################### condition: {} ###########################", condition);

// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //         }

        
// //         fmt::println("\n");

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}", balanceString);
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }


// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid,90,2\n"));


// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::SELL, 2_dec, 90_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 1_dec, 90_dec, 1_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent1, bookId, OrderDirection::BUY, 2_dec, 90_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec, 1_dec);
// //                 break;
// //         }
        


// //         fmt::println("\n");
// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}", balanceString);
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }


// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid\n"));

        
// //         //===========================================
// //         switch(condition){
// //             case 1:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //             case 2:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //             case 3:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 4:
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 5:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 6:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 break;
// //             case 7:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //             case 8:
// //                 placeLimitOrder(exchange, agent0, bookId, OrderDirection::BUY, 2_dec, 110_dec);
// //                 placeLimitOrder(exchange, agent2, bookId, OrderDirection::SELL, 2_dec, 110_dec);
// //                 break;
// //         }

        
// //         //placeLimitOrder(exchange, agent0, bookId, OrderDirection::SELL, 1_dec, 90_dec);

// //         // EXPECT_THAT(
// //         //     normalizeOutput(taosim::util::captureOutput([&] { book->printCSV(); })),
// //         //     StrEq("ask,101,1\n"
// //         //         "bid\n"));

// //         fmt::println("\n");
// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("========== Agent {} ==========", agId);
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].base.getLoans()){
// //                 fmt::println("*** Base  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             for (auto [loan_id, loan] : exchange.accounts()[agId][bookId].quote.getLoans()){
// //                 fmt::println("*** Quote  loanId:{}  | {} {} {} | {} ", loan_id, loan.volume, loan.price, loan.amount, loan.marginCall);
// //             }
// //             fmt::println("------------------------------------");
// //         }

// //         for (AgentId agId = -1; agId > -4; agId--){
// //             fmt::println("#################### Agent {} ###################", agId);
// //             std::string balanceString = normalizeOutput(fmt::format("{}", exchange.accounts()[agId][bookId]));
// //             fmt::println("{}", balanceString);
// //             fmt::println("++++++++++++++++++++++++++++++++++++");
// //         }

        
// //         fmt::println("\n###############################################################################################");
// //         fmt::println("################################################################################################\n\n");
// //     }

// // }

// // INSTANTIATE_TEST_SUITE_P(
// //     SingleAgentMarketSell,
// //     MultiBookExchangeAgentTestFixture,
// //     Values(std::pair{Timestamp{10}, "SingleAgent.xml"}),
// //     [](const auto&) { return "SingleAgent"; });

// // //-------------------------------------------------------------------------


