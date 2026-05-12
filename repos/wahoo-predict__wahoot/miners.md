## Mining on Wahooτ - Rewards On Top of Rewards

### We Made Mining on Bittensor Easily Accessible

Here's the thing: Most Bittensor subnets have a high techincal barrier to entry for outsiders. We decided to allow users to mine on Bittensor without requiring running any Python code at all!

**Code and Servers are completely optional.** Just trade on Wahoo like you normally would, and watch the Tao rewards show up in your wallet. It's that simple.

If you can make a prediction and click a button, as well as create a Bittensor wallet, then you can mine. Period.

Do you have previous experience with Python/Bittensor? Then you're ahead of the curve. Check out [our developer guide](#step-4-optional-create-api-keys) for more info.

### Get Started in 3 Steps

#### Step 1: Get Your Bittensor Wallet

You'll need a Bittensor wallet with a hotkey. Never heard of that? Totally fine. The [official Bittensor docs](https://docs.learnbittensor.org/miners) have your back. It's basically like setting up any crypto wallet – follow the steps, and you're golden.

Want more information or assistance on getting your wallet set up? The [Bittensor Community Discord server](https://discord.gg/bittensor) has you covered. After joining, we recommend familiarizing yourself with the [FAQ Channel](https://discord.com/channels/799672011265015819/1215386737661055056) for any initial questions regarding Bittensor. 

**NOTE - scammers will attempt you contact you via Direct Messages posing as Moderators/Admins shortly after joining the server. Only communicate with individuals within the official server and NEVER provide your recovery phrase / wallet password to anybody.**

#### Step 2: Register on Our Subnet

You will need some TAO funded on your wallet in order to register to any subnet in Bittensor. For information on how to load TAO onto your wallet, please refer to [the following guide](https://discord.com/channels/799672011265015819/1411009572092776600).

After you fund your wallet with some TAO, you can run the following command to register your newly created wallet to Wahoo:

```bash
btcli subnets register --netuid 30 --wallet.name WALLET_NAME --hotkey WALLET_HOTKEY
```

For more information about the available btcli commands and available arguments, please refer to the [btcli Reference Document](https://docs.learnbittensor.org/btcli)

#### Step 3: Link Everything Together

Pop over to [Wahoo](https://wahoopredict.com/en/auth/login?tab=register) and create an account. After creating an account, be sure to [verify your email address](https://account.wahoopredict.com/en/settings) as well as [adding your registered Hotkey](https://account.wahoopredict.com/en/settings?tab=bittensor-wallet) to your account. 

![wallet-linking-image](/images/wallet-linking.jpg)

You will have to verify that you own the hotkey address you provided by signing a message with your hotkey. Input your hotkey as the wallet address and obtain a verification messsage and sign the message with your wallet hotkey using the following btcli command:

```bash
btcli wallet sign --use-hotkey --wallet.name REGISTERED_WALLET --wallet.hotkey REGISTERED_HOTKEY --message "PASTE ENTIRE VERFICATION MESSAGE"
```

After receiving a Signature from `btcli`, input the signature within the appropriate field. Note that the verification message will expire after 5 minutes. Once your hotkey is linked to your account and said hotkey is registered as a miner, you can start trading to earn Tao!

### Trade and Earn

Once you're set up, **just trade like you always do**:

- Browse events at [Wahooτ](https://wahoopredict.com/?utm_source=subnet) – see what's hot
- Make your calls – Yes or No, that's it
- Watch your positions – manage your trades, see how you're doing

Meanwhile, in the background, we're tracking:
- **Your trading volume** → More activity = more rewards
- **Your profits** → Making money? Get rewarded for it
- **Your accuracy** → Right more often? That's worth something


You will need appropriate capital to trade via Wahooτ. Wahooτ accepts both fiat currency as well as various cryptocurrencies. Please head on over to the [cashier](https://account.wahoopredict.com/en/cashier?tab=deposit) to fund your account. 

Ready to withdraw your winnings? Not a problem! All you need is an appropriate receiving address for one of the many cryptocurrencies listed by Wahooτ. 

**Note - If depositing cryptocurrencies, ensure that you are transferring balance via the appropriate network. If you attempt to transfer on a network which your original balance is not a part of, this will result in an unrecoverable loss of funds.** 

#### Step 4 (Optional): Create API keys

Don't want to trade manually? The Wahooτ API provides live data on open markets as well as the ability to place trades. We'll leave this up to you to configure your own strategy or train a model based on the available data. Simply [generate an API key](https://account.wahoopredict.com/en/settings?tab=api-key-management) and keep your secret safe (this is used as your Authorization token in requests). 

For more information about the available endpoints, please refer to Wahooτ's [official API documentation](https://wahoopredict.gitbook.io/wahoopredict-docs/api/api-for-developers).

#### Step 5 - Even More Rewards!

Do you want even more rewards for participating on Wahooτ? Look no further than the [Referral Program](https://account.wahoopredict.com/en/referrals)! By spreading the word of Wahooτ, you get rewarded with every prediction made by users that you referred!