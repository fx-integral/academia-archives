// SPDX-License-Identifier: GPL-3.0

pragma solidity ^0.8.24;

import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts/utils/math/Math.sol";
import "./stakingV2.sol";
import "./alpha.sol";
import "./LoanLib.sol";


contract LendingPoolV2Upgradeable is Initializable, OwnableUpgradeable, ReentrancyGuardUpgradeable {

    uint64 public VERSION; // Contract version, incremented on each upgrade

    bytes32 public CONTRACT_COLDKEY;
    bytes32 public TREASURY_COLDKEY;
    bytes32 public FEE_RECEIVER_COLDKEY;
    bytes32 public DELEGATE_HOTKEY;
    address public MANAGER;
    uint256 public MIN_LOAN_DURATION; // blocks

    uint256 public FEE_RATE; // 30% fee on interest by default
    uint256 constant SAFE_ALPHA_PRICE = 9_000; // 90% safety margin
    uint256 constant RATE_BASE = 10_000;

    uint256 constant MAX_DAY_RATE = 10_000_000; // 1% - maximum daily rate
    uint256 constant MIN_DAY_RATE = 100_000; // 0.01% - minimum daily rate
    uint256 constant PRICE_BASE = 1e9;

    uint256 public constant MIN_POOL_ALPHA_THRESHOLD = 108_000 * 1e9; // 15 days alpha emission
    uint256 public constant MIN_LOAN_AMOUNT = 1e9; // 1 TAO minimum

    uint256 constant BLOCKS_PER_DAY = 7200;

    bool public pausedBorrow;
    bool public pausedTransfer;
    bool public pausedRefinance;
    bool public pausedDeposit;

    IStaking public staking;
    IAlpha public alpha;

    mapping (address => mapping(uint16 => uint256)) public userAlphaBalance; // [address][netuid] => alpha balance
    mapping (uint16 => uint256) public subnetAlphaBalance; // netuid => subnet total user alpha balance

    // Loan offer related mappings
    mapping (uint256 => LoanTerm) public loanTerms;  // loanId => LoanTerm
    mapping (uint256 => LoanData) public loanRecords; // loanDataId => LoanData
    mapping (bytes32 => Offer) public loanOffers; // offerId => Offer
    mapping (bytes32 => uint256) public canceledOffers; // offerId => cancellation timestamp
    mapping (address => uint256) public lenderNonce;  // lender => current nonce
    mapping (address => mapping(bytes32 => uint256)) public userLendBalance; // [address][offerId] => amount lent out of offer

    uint256 public nextLoanId;  // Auto-incrementing loan ID counter
    uint256 public nextLoanDataId; // Auto-increasing loan data Id counter
    mapping (uint16 => bool) public activeSubnets; // netuid => active status

    uint256 public protocolFeeAccumulated; // Accumulated protocol fees

    mapping (address => bool) public registeredUser;
    mapping (address => bytes32) public userColdkey; // address => SS58 coldkey, which is converted from address

    // v2 add
    mapping (uint16 => uint16) public subnetMaxLevels; // netuid => max level (e.g. 150 means 150%)

    event RegisterUser(
        address indexed user,
        bytes32 indexed coldkey
    );

    event DepositAlpha(
        address indexed sender,
        uint16 netuid,
        uint256 amount,
        bytes32 delegateHotkey,
        address to
    );
    event WithdrawAlpha(
        address indexed sender,
        uint16 netuid,
        uint256 amount,
        bytes32 delegateHotkey,
        bytes32 userColdkey
    );
    event DepositTao(
        address indexed sender,
        uint256 amount
    );
    event WithdrawTao(
        address indexed sender,
        uint256 amount
    );
    event WithdrawRewardAlpha(
        address indexed sender,
        uint16 netuid,
        uint256 amount,
        bytes32 indexed to
    );
    event WithdrawEmergencyTao(
        address indexed sender,
        uint256 amount,
        bytes32 indexed to
    );
    event WithdrawProtocolFees(
        address indexed sender,
        uint256 amount,
        bytes32 indexed to
    );

    event CancelOffer(
        address indexed lender,
        bytes32 indexed offerId,
        uint16 indexed netuid
    );

    event CancelAllOffers(
        address indexed lender,
        uint256 indexed nonce
    );

    // Loan events
    event CreateLoan(
        address indexed borrower,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 userCollateralAmount,
        uint256 loanCollateralAmount,
        uint256 loanAmount,
        uint256 dailyInterestRate,
        uint8 loanType // 0 for normal borrow, 1 for level borrow, 2 for buy level
    );

    event RepayLoan (
        address indexed borrower,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 repayAmount,
        uint256 protocolFee,
        uint256 sellAmount,
        uint256 sellPrice
    );

    event CollectLoan(
        address indexed lender,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 loanAmount
    );

    event TransferLoan(
        address indexed initiator,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 loanAmount,
        uint256 dailyInterestRate,
        uint256 oldLoanDataId,
        bytes32 oldOfferId,
        uint256 oldLoanAmount,
        uint256 repayAmount,
        uint256 protocolFee
    );

    event RefinanceLoan(
        address indexed initiator,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 loanAmount,
        uint256 dailyInterestRate,
        uint256 oldLoanDataId,
        bytes32 oldOfferId,
        uint256 oldLoanAmount,
        uint256 repayAmount,
        uint256 protocolFee
    );

    event SeizeLoan(
        address indexed lender,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 loanAmount
    );

    event ResolveLoan(
        address indexed admin,
        uint256 indexed loanId,
        uint256 indexed loanDataId,
        bytes32 offerId,
        uint16 netuid,
        uint256 block,
        uint256 collateralAmount,
        uint256 lenderAmount,
        uint256 borrowerAmount
    );

    event ResolveAlpha(
        address indexed admin,
        address indexed user,
        uint16 netuid,
        uint256 alphaAmount,
        uint256 taoAmount
    );

    event SetPauseStatus(string accepted, bool paused);

    event SetFeeRate(uint256 oldRate, uint256 newRate);

    event SetMaxLevel(uint16 netuid, uint16 maxLevel);

    event ActiveSubnet(uint16 netuid, bool active);

    modifier onlyManager() {
        require(MANAGER == msg.sender, "not manager");
        _;
    }

    modifier onlyRegistered() {
        require(registeredUser[msg.sender], "not registered");
        _;
    }

    modifier nonPausedBorrow() {
        require(!pausedBorrow, "paused borrow");
        _;
    }

    modifier nonPausedTransfer() {
        require(!pausedTransfer, "paused transfer");
        _;
    }

    modifier nonPausedRefinance() {
        require(!pausedRefinance, "paused refinance");
        _;
    }

    modifier nonPausedDeposit() {
        require(!pausedDeposit, "paused deposit");
        _;
    }

    modifier verifyOffer(Offer memory _offer) {
        require(_offer.expire > block.timestamp, "offer expired");
        require(_offer.nonce == lenderNonce[_offer.lender], "bad nonce");
        require(canceledOffers[_offer.offerId] == 0, "offer canceled");
        require(_offer.netuid > 0, "bad netuid");
        require(_offer.dailyInterestRate >= MIN_DAY_RATE && _offer.dailyInterestRate <= MAX_DAY_RATE, "bad rate");
        require(_offer.offerId == LoanLib.calculateOfferId(_offer), "bad offer id");
        require(LoanLib.verifyOfferSignature(_offer), "bad signature");
        _;
    }

    /**
     * @dev Initialize the contract (replaces constructor for upgradeable pattern)
     * @param _delegateHotkey The delegate hotkey for staking
     * @param _treasuryColdkey The treasury coldkey for protocol operations
     * @param _feeReceiverColdkey The fee receiver coldkey
     * @param _manager The manager address for admin operations
     * @param _minLoanDuration Minimum loan duration in blocks
     */
    function initialize(
        bytes32 _delegateHotkey,
        bytes32 _treasuryColdkey,
        bytes32 _feeReceiverColdkey,
        address _manager,
        uint256 _minLoanDuration
    ) public initializer {
        __Ownable_init(msg.sender);
        __ReentrancyGuard_init();

        DELEGATE_HOTKEY = _delegateHotkey;
        TREASURY_COLDKEY = _treasuryColdkey;
        FEE_RECEIVER_COLDKEY = _feeReceiverColdkey;
        MANAGER = _manager;
        MIN_LOAN_DURATION = _minLoanDuration;

        // Initialize precompiled contract interfaces
        staking = IStaking(ISTAKING_ADDRESS);
        alpha = IAlpha(IALPHA_ADDRESS);

        // Initialize default values
        VERSION = 1; // Initial version
        FEE_RATE = 3_000; // 30% fee
        pausedBorrow = false;
        pausedTransfer = false;
        pausedRefinance = false;
        pausedDeposit = false;
        nextLoanId = 0;
        nextLoanDataId = 0;
        protocolFeeAccumulated = 0;

        // Enable subnet 0 by default
        activeSubnets[0] = true;

        // Set CONTRACT_COLDKEY to placeholder (will be set later via setContractColdkey)
        CONTRACT_COLDKEY = bytes32(0);
    }

    /**
     * @dev Set CONTRACT_COLDKEY after deployment (one-time setter)
     * @param _coldkey The contract's coldkey derived from proxy address
     */
    function setContractColdkey(bytes32 _coldkey) public onlyOwner {
        require(CONTRACT_COLDKEY == bytes32(0) && _coldkey != bytes32(0), "coldkey already set or invalid");
        CONTRACT_COLDKEY = _coldkey;
    }

    /**
     * @dev Reinitialize contract after upgrade (increments VERSION)
     * @param _version The new version number (must be greater than current VERSION)
     * @custom:oz-upgrades-validate-as-initializer
     */
    function reinitialize(uint64 _version) public reinitializer(_version) {
        // Increment VERSION to track upgrade
        VERSION = _version;
    }

    function setPausedBorrow(bool _paused) public onlyOwner {
        pausedBorrow = _paused;
        emit SetPauseStatus("BORROW", _paused);
    }

    function setPausedTransfer(bool _paused) public onlyOwner {
        pausedTransfer = _paused;
        emit SetPauseStatus("TRANSFER", _paused);
    }

    function setPausedRefinance(bool _paused) public onlyOwner {
        pausedRefinance = _paused;
        emit SetPauseStatus("REFINANCE", _paused);
    }

    function setPausedDeposit(bool _paused) public onlyOwner {
        pausedDeposit= _paused;
        emit SetPauseStatus("DEPOSIT", _paused);
    }

    function setFeeRate(uint256 _feeRate) public onlyOwner {
        require(_feeRate <= RATE_BASE, "bad fee rate");
        uint256 oldRate = FEE_RATE;
        FEE_RATE = _feeRate;
        emit SetFeeRate(oldRate, _feeRate);
    }

    /**
     * @dev Create a new loan
     * @param _offer The offer struct with valid signature
     * @param _taoAmount The amount of TAO to borrow, decimal RAO(1e9)
     * @param _alphaAmount The amount of ALPHA to collateralize
     */
    function borrow(Offer memory _offer, uint256 _taoAmount, uint256 _alphaAmount)
        external onlyRegistered  verifyOffer(_offer)
        nonPausedBorrow nonReentrant returns (uint256)
    {
        _requireSubnetActive(_offer.netuid);
        require(_taoAmount <= type(uint64).max, "tao amount overflow");
        require(_taoAmount >= MIN_LOAN_AMOUNT, "loan too small");
        require(userAlphaBalance[msg.sender][_offer.netuid] >= _alphaAmount, "low alpha");

        _lenderBalanceChecker(_offer, _taoAmount);
        _alphaPriceChecker(_offer, _taoAmount, _alphaAmount);

        _decreaseUserAlphaBalance(msg.sender, _offer.netuid, _alphaAmount);
        _updateLenderBorrowBalance(_offer, _taoAmount);

        // New loan creation and return TAO to borrower
        uint256 loanId = _newLoan(_offer, _taoAmount, _alphaAmount);
        uint256 removedStake = _removeStake(_taoAmount, 0);
        _decreaseSubnetAlphaBalance(0, removedStake);
        _transferTao(msg.sender, removedStake);

        emit CreateLoan(
            msg.sender,
            loanId,
            loanTerms[loanId].loanDataId,
            _offer.offerId,
            _offer.netuid,
            block.number,
            _alphaAmount,
            _alphaAmount,
            _taoAmount,
            _offer.dailyInterestRate,
            0 // loan type 0 for normal borrow
        );

        return loanId;
    }

    /**
     * @dev Create a new loan with level borrow
     * @param _offer The offer struct with valid signature
     * @param _borrowTaoAmount The amount of TAO to borrow, decimal RAO(1e9)
     * @param _alphaAmount The amount of ALPHA to collateralize
     * @param _limitAlphaPrice The buy alpha limit price
     */
    function borrowLevel(Offer memory _offer, uint256 _borrowTaoAmount, uint256 _alphaAmount, uint256 _limitAlphaPrice)
        external onlyRegistered verifyOffer(_offer)
        nonPausedBorrow nonReentrant returns (uint256)
    {
        _requireSubnetActive(_offer.netuid);
        require(msg.sender != _offer.lender, "self lending");
        require(_borrowTaoAmount <= type(uint64).max, "tao amount overflow");
        require(_borrowTaoAmount >= MIN_LOAN_AMOUNT, "loan too small");
        require(_alphaAmount > 0 && userAlphaBalance[msg.sender][_offer.netuid] >= _alphaAmount, "low alpha");
        _lenderBalanceChecker(_offer, _borrowTaoAmount);

        // level check
        uint16 maxLevel = subnetMaxLevels[_offer.netuid];
        require(
            maxLevel > 0 && _borrowTaoAmount * PRICE_BASE * 100 <= _alphaAmount * _offer.maxAlphaPrice * maxLevel, 
            "bad level"
        );

        // sim check
        uint256 simAlphaAmount = alpha.simSwapTaoForAlpha(_offer.netuid, uint64(_borrowTaoAmount));
        {

            uint256 simAlphaPrice = _borrowTaoAmount * PRICE_BASE / simAlphaAmount;
            require(_limitAlphaPrice > 0 && simAlphaPrice < _limitAlphaPrice, "limit price too low");
            _simAlphaPriceChecker(_offer, _borrowTaoAmount, simAlphaAmount + _alphaAmount, simAlphaPrice);
        }

        _decreaseUserAlphaBalance(msg.sender, _offer.netuid, _alphaAmount);
        _updateLenderBorrowBalance(_offer, _borrowTaoAmount);

        // unstake TAO and buy alpha for level borrow
        uint256 removedStake = _removeStake(_borrowTaoAmount, 0);
        _decreaseSubnetAlphaBalance(0, removedStake);
        uint256 buyAlphaAmount = _addStake(removedStake, _offer.netuid);
        require(buyAlphaAmount * 100 > simAlphaAmount * 95, "insufficient alpha bought");
        _increaseSubnetAlphaBalance(_offer.netuid, buyAlphaAmount);

        // New loan creation and return TAO to borrower
        uint256 loanId = _newLoan(_offer, _borrowTaoAmount, _alphaAmount + buyAlphaAmount);

        emit CreateLoan(
            msg.sender,
            loanId,
            loanTerms[loanId].loanDataId,
            _offer.offerId,
            _offer.netuid,
            block.number,
            _alphaAmount,
            _alphaAmount + buyAlphaAmount,
            _borrowTaoAmount,
            _offer.dailyInterestRate,
            1 // loan type 1 for level borrow
        );

        return loanId;
    }

    /**
     * @dev Repay a loan
     * @param _loanId The ID of the loan to repay
     */
    function repay(uint256 _loanId) external onlyRegistered nonReentrant {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory offer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireLoanActive(loanData);
        _requireSubnetActive(netuid);

        (uint256 repayAmount, uint256 protocolFee) = _settleLoanRepayment(loanData);
        require(userAlphaBalance[msg.sender][0] >= repayAmount, "low tao");

        _decreaseUserAlphaBalance(msg.sender, 0, repayAmount);
        _increaseUserAlphaBalance(loanTerm.borrower, netuid, loanTerm.collateralAmount);

        emit RepayLoan(
            msg.sender,
            _loanId,
            loanTerm.loanDataId,
            offer.offerId,
            netuid,
            block.number,
            loanTerm.collateralAmount,
            repayAmount - protocolFee,
            protocolFee,
            0, // sell amount 0 for normal repay
            0
        );
    }

    /**
     * @dev Create a new loan of level
     * @param _offer The offer struct with valid signature
     * @param _collateralTaoAmount The amount of TAO to collateralize
     * @param _borrowTaoAmount The borrow TAO amount
     * @param _limitAlphaPrice The buy alpha limit price
     */
    function buyLevel(Offer memory _offer, uint256 _collateralTaoAmount, uint256 _borrowTaoAmount, uint256 _limitAlphaPrice)
        external onlyRegistered  verifyOffer(_offer)
        nonPausedBorrow nonReentrant returns (uint256)
    {
        _requireSubnetActive(_offer.netuid);
        require(msg.sender != _offer.lender, "self lending");
        require((_collateralTaoAmount + _borrowTaoAmount) <= type(uint64).max, "tao amount overflow");
        require(_borrowTaoAmount >= MIN_LOAN_AMOUNT, "loan too small");
        require(_collateralTaoAmount > 0 && userAlphaBalance[msg.sender][0] >= _collateralTaoAmount, "low tao");
        _lenderBalanceChecker(_offer, _borrowTaoAmount);

        uint16 maxLevel = subnetMaxLevels[_offer.netuid];
        require(maxLevel > 0 && _borrowTaoAmount * 100 <= _collateralTaoAmount * maxLevel, "bad level");
        
        // sim check
        uint256 simAlphaAmount = alpha.simSwapTaoForAlpha(_offer.netuid, uint64(_collateralTaoAmount + _borrowTaoAmount));
        {
            uint256 simAlphaPrice = (_collateralTaoAmount + _borrowTaoAmount) * PRICE_BASE / simAlphaAmount;
            require(_limitAlphaPrice > 0 && simAlphaPrice < _limitAlphaPrice, "limit price too low");
            _simAlphaPriceChecker(_offer, _borrowTaoAmount, simAlphaAmount, simAlphaPrice);
        }

        _decreaseUserAlphaBalance(msg.sender, 0, _collateralTaoAmount);
        _updateLenderBorrowBalance(_offer, _borrowTaoAmount);

        // unstake TAO and buy alpha
        uint256 removedStake = _removeStake(_collateralTaoAmount + _borrowTaoAmount, 0);
        _decreaseSubnetAlphaBalance(0, removedStake);
        uint256 buyAlphaAmount = _addStake(removedStake, _offer.netuid);
        require(buyAlphaAmount * 100 > simAlphaAmount * 95, "insufficient alpha bought");
        _increaseSubnetAlphaBalance(_offer.netuid, buyAlphaAmount);

        // New loan creation
        uint256 loanId = _newLoan(_offer, _borrowTaoAmount, buyAlphaAmount);

        emit CreateLoan(
            msg.sender,
            loanId,
            loanTerms[loanId].loanDataId,
            _offer.offerId,
            _offer.netuid,
            block.number,
            _collateralTaoAmount,
            buyAlphaAmount,
            _borrowTaoAmount,
            _offer.dailyInterestRate,
            2 // loan type 2 for buy level
        );

        return loanId;
    }

    /**
     * @dev Repay a loan by sell collateral alpha
     * @param _loanId The ID of the loan to repay
     * @param _alphaAmount The sell amount of collateral
     * @param _limitAlphaPrice The buy alpha limit price
     */
    function repayBySell(uint256 _loanId, uint256 _alphaAmount, uint256 _limitAlphaPrice)
        external onlyRegistered nonReentrant
    {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory offer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireLoanActive(loanData);
        _requireSubnetActive(netuid);

        require(_alphaAmount <= type(uint64).max, "alpha amount overflow"); 
        require(loanTerm.borrower == msg.sender, "not borrower");
        require(loanTerm.collateralAmount >= _alphaAmount, "collateral not enough");

        (uint256 repayAmount, uint256 protocolFee) = _settleLoanRepayment(loanData);

        // sim check
        uint256 simTaoAmount = alpha.simSwapAlphaForTao(offer.netuid, uint64(_alphaAmount));
        {
            require(userAlphaBalance[msg.sender][0] + simTaoAmount >= repayAmount, "low tao");
            uint256 simAlphaPrice = simTaoAmount * PRICE_BASE / _alphaAmount;
            require(_limitAlphaPrice > 0 && _limitAlphaPrice < simAlphaPrice, "limit price too high");
        }

        // sell alpha and stake TAO
        uint256 sellTaoAmount = _removeStake(_alphaAmount, offer.netuid);
        require(sellTaoAmount * 100 > simTaoAmount * 95, "insufficient tao sold");
        _decreaseSubnetAlphaBalance(offer.netuid, _alphaAmount);
        uint256 stakedAmount = _addStake(sellTaoAmount, 0);
        require(userAlphaBalance[msg.sender][0] + stakedAmount >= repayAmount, "low tao");
        _increaseUserAlphaBalance(msg.sender, 0, stakedAmount);
        _increaseSubnetAlphaBalance(0, stakedAmount);

        _decreaseUserAlphaBalance(msg.sender, 0, repayAmount);
        _increaseUserAlphaBalance(loanTerm.borrower, netuid, loanTerm.collateralAmount - _alphaAmount);

        emit RepayLoan(
            msg.sender,
            _loanId,
            loanTerm.loanDataId,
            offer.offerId,
            netuid,
            block.number,
            loanTerm.collateralAmount,
            repayAmount - protocolFee,
            protocolFee,
            _alphaAmount,
            sellTaoAmount * 1e9 / _alphaAmount
        );
    }

    /**
     * @dev Transfer a loan to new lender
     * @param _loanId The ID of the loan to transfer
     * @param _offer The new offer details
     */
    function transfer(uint256 _loanId, Offer memory _offer)
        external onlyRegistered verifyOffer(_offer) nonPausedTransfer nonReentrant
    {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory oldOffer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireLoanActive(loanData);
        _requireSubnetActive(netuid);

        require(_offer.netuid == netuid, "netuid mismatch");
        require(oldOffer.lender != _offer.lender, "same lender");
        require(_offer.dailyInterestRate <= oldOffer.dailyInterestRate * 150 / 100, "day rate too high"); // limit increasing 50%

        if (msg.sender == oldOffer.lender) {
            // lender can transfer from OPEN and COLLECTED state, if from OPEN state, must be active for at least MIN_LOAN_DURATION
            if (loanData.state == STATE.OPEN) {
                require(block.number > loanData.startBlock + MIN_LOAN_DURATION, "too early");
            }
        } else {
            // only COLLECTED state can be transferred by anyone else
            require(loanData.state == STATE.IN_COLLECTION, "not collecting");
        }

        (uint256 repayAmount, uint256 protocolFee) = _settleLoanRepayment(loanData);

        _lenderBalanceChecker(_offer, repayAmount);
        _alphaPriceChecker(_offer, repayAmount, loanTerm.collateralAmount);

        _updateLenderBorrowBalance(_offer, repayAmount);

        uint256 loanDataId = _newLoanData(
            _loanId,
            _offer,
            repayAmount
        );
        uint256 oldLoanDataId = loanTerm.loanDataId;
        _updateLoanTerm(loanTerm, loanDataId);

        emit TransferLoan(
            msg.sender,
            _loanId,
            loanDataId,
            _offer.offerId,
            netuid,
            block.number,
            loanTerm.collateralAmount,
            repayAmount,
            _offer.dailyInterestRate,
            // old loan info
            oldLoanDataId,
            oldOffer.offerId,
            loanData.loanAmount,
            repayAmount - protocolFee,
            protocolFee
        );
    }

    /**
     * @dev Refinance a loan with a new offer
     * @param _loanId The ID of the loan to refinance
     * @param _offer The new offer details
     * @param _newLoanAmount The new loan amount in RAO
     */
    function refinance(uint256 _loanId, Offer memory _offer, uint256 _newLoanAmount)
        external onlyRegistered verifyOffer(_offer) nonPausedRefinance nonReentrant
    {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory oldOffer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireLoanActive(loanData);
        _requireSubnetActive(netuid);

        // only borrower can refinance
        require(loanTerm.borrower == msg.sender, "not borrower");
        require(_offer.netuid == netuid, "netuid mismatch");
        require(_newLoanAmount >= MIN_LOAN_AMOUNT, "loan too small");

        (uint256 repayAmount, uint256 protocolFee) = _settleLoanRepayment(loanData);

        _lenderBalanceChecker(_offer, _newLoanAmount);
        _alphaPriceChecker(_offer, _newLoanAmount, loanTerm.collateralAmount);

        // borrow less TAO
        if (_newLoanAmount < repayAmount) {
            uint256 additionalPayment = repayAmount - _newLoanAmount;
            // check borrower balance
            require(userAlphaBalance[msg.sender][0] >= additionalPayment, "low tao");
            _decreaseUserAlphaBalance(msg.sender, 0, additionalPayment);
        }
        // borrow more TAO
        uint256 additionalBorrowAmount = 0;
        if (_newLoanAmount > repayAmount) {
            additionalBorrowAmount = _newLoanAmount - repayAmount;
            additionalBorrowAmount = _removeStake(additionalBorrowAmount, 0);
            _decreaseSubnetAlphaBalance(0, additionalBorrowAmount);
        }

        _updateLenderBorrowBalance(_offer, _newLoanAmount);

        uint256 loanDataId = _newLoanData(
            _loanId,
            _offer,
            _newLoanAmount
        );
        uint256 oldLoanDataId = loanTerm.loanDataId;
        _updateLoanTerm(loanTerm, loanDataId);

        // return TAO to borrower if any
        if (additionalBorrowAmount > 0) {
            _transferTao(msg.sender, additionalBorrowAmount);
        }

        emit RefinanceLoan(
            msg.sender,
            _loanId,
            loanDataId,
            _offer.offerId,
            loanTerm.netuid,
            block.number,
            loanTerm.collateralAmount,
            _newLoanAmount,
            _offer.dailyInterestRate,
            // old loan info
            oldLoanDataId,
            oldOffer.offerId,
            loanData.loanAmount,
            repayAmount - protocolFee,
            protocolFee
        );
    }

    /**
     * @dev Liquidate a loan (when conditions are met)
     * @param _loanId The ID of the loan to liquidate
     */
    function collect(uint256 _loanId) external onlyRegistered nonReentrant {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory offer) = _getLoanData(_loanId);

        _requireSubnetActive(loanTerm.netuid);
        require(loanData.state == STATE.OPEN, "not active");
        require(offer.lender == msg.sender, "not lender");
        require(block.number > loanData.startBlock + MIN_LOAN_DURATION, "too early");

        _updateLoanData(loanData, STATE.IN_COLLECTION);

        emit CollectLoan(
            msg.sender,
            _loanId,
            loanTerm.loanDataId,
            offer.offerId,
            loanTerm.netuid,
            loanData.startBlock,
            loanTerm.collateralAmount,
            loanData.loanAmount
        );
    }

    /**
     * @dev Claim a loan (when conditions are met)
     * @param _loanId The ID of the loan to claim
     */
    function seize(uint256 _loanId) external onlyRegistered nonReentrant {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory offer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireSubnetActive(netuid);
        require(loanData.state == STATE.IN_COLLECTION, "not collecting");
        require(offer.lender == msg.sender, "not lender");
        // check time from last update (collect)
        require(block.number > loanData.lastUpdateBlock + MIN_LOAN_DURATION, "too early");

        _increaseUserAlphaBalance(msg.sender, netuid, loanTerm.collateralAmount);
        _updateLenderRepayBalance(loanData, 0);

        _updateLoanData(loanData, STATE.CLAIMED);

        emit SeizeLoan(
            msg.sender,
            _loanId,
            loanTerm.loanDataId,
            offer.offerId,
            netuid,
            loanData.startBlock,
            loanTerm.collateralAmount,
            loanData.loanAmount
        );
    }

    /**
     * @dev Cancel a loan offer (only by lender)
     * @param _offer The loan offer to cancel
     */
    function cancel(Offer memory _offer) external onlyRegistered verifyOffer(_offer) nonReentrant {
        require(_offer.lender == msg.sender, "not lender");

        canceledOffers[_offer.offerId] = block.number;

        emit CancelOffer(msg.sender, _offer.offerId, _offer.netuid);
    }

    /**
     * @dev Cancel all loan offers for the sender (by incrementing nonce)
     */
    function cancel() external onlyRegistered nonReentrant {
        uint256 currentNonce = lenderNonce[msg.sender];
        lenderNonce[msg.sender]++;

        emit CancelAllOffers(msg.sender, currentNonce);
    }

    /**
     * @dev Register a user with their coldkey, the coldkey MUST be SS58 address derived from msg.sender
     * @param _coldkey The user's coldkey
     * @param _signature The signature of the coldkey signed by the user's address
     */
    function register(bytes32 _coldkey, bytes memory _signature) external  nonReentrant {
        require(!registeredUser[msg.sender], "registered");

        // Verify signature: check that _coldkey was signed by msg.sender
        require(
            LoanLib.verifySignature(_coldkey, _signature, msg.sender),
            "invalid signature: message must be signed by msg.sender"
        );
        registeredUser[msg.sender] = true;
        userColdkey[msg.sender] = _coldkey;

        emit RegisterUser(msg.sender, _coldkey);
    }

    /**
     * @dev Deposit TAO into the lending pool, and stake it automatically
     */
    function depositTao() external  payable onlyRegistered nonPausedDeposit nonReentrant {
        uint256 rao = msg.value / 1e9; // Convert EVM TAO (18 decimals) to RAO (9 decimals)
        require(rao > 0, "zero amount");

        uint256 stakedAmount = _addStake(rao, 0);
        uint256 creditAmount = Math.min(stakedAmount, rao);
        _increaseUserAlphaBalance(msg.sender, 0, creditAmount);
        _increaseSubnetAlphaBalance(0, creditAmount);

        emit DepositTao(msg.sender, creditAmount);
    }

    /**
     * @dev Withdraw TAO from the lending pool
     * @param _amount The amount of TAO to withdraw (in RAO)
     */
    function withdrawTao(uint256 _amount) external onlyRegistered  nonReentrant {
        require(userAlphaBalance[msg.sender][0] >= _amount, "low tao");

        _decreaseUserAlphaBalance(msg.sender, 0, _amount);
        _decreaseSubnetAlphaBalance(0, _amount);

        uint256 removedStake = _removeStake(_amount, 0);
        _transferTao(msg.sender, removedStake);

        emit WithdrawTao(msg.sender,_amount);
    }

    /**
     * @dev Deposit ALPHA into the lending pool, and move it to the default staking delegate if not same as delegate hotkey
     * @param _netuid The subnet ID
     * @param _amount The amount of ALPHA to deposit
     * @param _delegateHotkey The delegate hotkey for staking ALPHA
     */
    function depositAlpha(uint16 _netuid, uint256 _amount, bytes32 _delegateHotkey)
        external onlyRegistered  nonPausedDeposit nonReentrant
    {
        _requireSubnetActive(_netuid);

        uint256 stakedAmount = _depositAlpha(_netuid, _amount, _delegateHotkey);
        uint256 creditAmount = Math.min(stakedAmount, _amount);
        _increaseUserAlphaBalance(msg.sender, _netuid, creditAmount);
        _increaseSubnetAlphaBalance(_netuid, creditAmount);

        emit DepositAlpha(msg.sender, _netuid, creditAmount, _delegateHotkey, msg.sender);
    }

    /**
     * @dev Deposit ALPHA into the lending pool, and move it to the default staking delegate if not same as delegate hotkey
     * @param _netuid The subnet ID
     * @param _amount The amount of ALPHA to deposit
     * @param _delegateHotkey The delegate hotkey for staking ALPHA
     * @param _to The address to credit the deposited ALPHA
     */
    function depositAlpha(uint16 _netuid, uint256 _amount, bytes32 _delegateHotkey, address _to)
        external onlyRegistered nonPausedDeposit nonReentrant
    {
        _requireSubnetActive(_netuid);
        require(_to != address(0), "zero address");

        uint256 stakedAmount = _depositAlpha(_netuid, _amount, _delegateHotkey);
        uint256 creditAmount = Math.min(stakedAmount, _amount);
        _increaseUserAlphaBalance(_to, _netuid, creditAmount);
        _increaseSubnetAlphaBalance(_netuid, creditAmount);

        emit DepositAlpha(msg.sender, _netuid, creditAmount, _delegateHotkey, _to);
    }

    /**
     * @dev Withdraw ALPHA from the lending pool
     * @param _netuid The subnet ID
     * @param _amount The amount of ALPHA to withdraw
     */
    function withdrawAlpha(uint16 _netuid, uint256 _amount)
        external onlyRegistered nonReentrant
    {
        _requireSubnetActive(_netuid);
        require(userAlphaBalance[msg.sender][_netuid] >= _amount, "low alpha");

        _decreaseUserAlphaBalance(msg.sender, _netuid, _amount);
        _decreaseSubnetAlphaBalance(_netuid, _amount);
        _withdrawAlpha(_netuid, _amount, userColdkey[msg.sender]);

        emit WithdrawAlpha(msg.sender, _netuid, _amount, DELEGATE_HOTKEY, userColdkey[msg.sender]);
    }

    /**
     * @dev Admin withdraw reward ALPHA, and just withdraw the staking rewards and make sure the user deposited ALPHA are not affected
     * @param _netuid The subnet ID
     * @param _amount The amount of ALPHA to withdraw
     */
    function withdrawRewardAlpha(uint16 _netuid, uint256 _amount)
        external onlyManager nonReentrant
    {
        _requireSubnetActive(_netuid);

        // allow withdrawal only from surplus stake (staking rewards),
        // defined as total stake minus total user-deposited alpha
        uint256 totalStake = staking.getStake(DELEGATE_HOTKEY, CONTRACT_COLDKEY, _netuid);
        uint256 withdrawableReward =
            totalStake > subnetAlphaBalance[_netuid]
                ? totalStake - subnetAlphaBalance[_netuid]
                : 0;
        require(withdrawableReward >= _amount, "low reward");

        _withdrawAlpha(_netuid, _amount, TREASURY_COLDKEY);

        emit WithdrawRewardAlpha(msg.sender, _netuid, _amount, TREASURY_COLDKEY);
    }

    /**
     * @dev Admin withdraw accumulated protocol fees(ALPHA 0)
     * @param _amount The amount of protocol fees to withdraw
     */
    function withdrawProtocolFees(uint256 _amount) external onlyManager nonReentrant {
        require(protocolFeeAccumulated >= _amount, "low fee");

        _decreaseFee(_amount);
        _decreaseSubnetAlphaBalance(0, _amount);
        _withdrawAlpha(0, _amount, FEE_RECEIVER_COLDKEY);

        emit WithdrawProtocolFees(msg.sender, _amount, FEE_RECEIVER_COLDKEY);
    }

    /**
     * @dev Admin enable a subnet for lending
     * @param _netuid The subnet ID
     */
    function enableSubnet(uint16 _netuid) external onlyManager nonReentrant {
        require(_netuid > 0, "bad netuid");
        require(_highAlphaInPool(_netuid), "low pool alpha");
        activeSubnets[_netuid] = true;

        emit ActiveSubnet(_netuid, true);
    }

    /**
     * @dev Admin disable a subnet for lending
     * @param _netuid The subnet ID
     */
    function disableSubnet(uint16 _netuid) external onlyManager nonReentrant {
        require(_netuid > 0, "bad netuid");
        require(_lowAlphaInPool(_netuid), "high pool alpha");
        activeSubnets[_netuid] = false;

        emit ActiveSubnet(_netuid, false);
    }

    /**
     * @dev Admin set collateralization level for a subnet
     * @param _netuid The subnet ID
     * @param _level The collateralization level (e.g. 150 means 150%)
     */
    function setMaxLevel(uint16 _netuid, uint16 _level) public onlyManager nonReentrant {
        require(_netuid > 0, "bad netuid");
        require(_level <= 500, "bad level");
        subnetMaxLevels[_netuid] = _level;
        emit SetMaxLevel(_netuid, _level);
    }

    /**
     * @dev Admin resolve a loan manually (in case of degistation)
     * @param _loanId The loan ID
     * @param _lenderAmount The amount to return to the lender (in TAO)
     * @param _borrowerAmount The amount to return to the borrower (in TAO)
     */
    function resolveLoan(uint256 _loanId, uint256 _lenderAmount, uint256 _borrowerAmount)
        external onlyManager nonReentrant
    {
        (LoanTerm storage loanTerm, LoanData storage loanData, Offer memory offer) = _getLoanData(_loanId);
        uint16 netuid = loanTerm.netuid;

        _requireLoanActive(loanData);
        require(!activeSubnets[netuid], "subnet enabled");
        require(_lowAlphaInPool(netuid), "high alpha");
        require(_lenderAmount > 0, "zero amount");

        uint256 contractTaoBalance = address(this).balance / 1e9;
        require(contractTaoBalance >= _lenderAmount + _borrowerAmount, "insufficient TAO");

        _updateLenderRepayBalance(loanData, _lenderAmount);
        _increaseUserAlphaBalance(loanTerm.borrower, 0, _borrowerAmount);
        _decreaseSubnetAlphaBalance(netuid, loanTerm.collateralAmount);

        _updateLoanData(loanData, STATE.RESOLVED);

        // deregistered TAO returned to staking pool, so stake it
        uint256 addedStake = _addStake(_borrowerAmount + _lenderAmount, 0);
        _increaseSubnetAlphaBalance(0, addedStake);

        emit ResolveLoan(
            msg.sender,
            _loanId,
            loanTerm.loanDataId,
            offer.offerId,
            netuid,
            block.number,
            loanTerm.collateralAmount,
            _lenderAmount,
            _borrowerAmount
        );
    }

    /**
     * @dev Admin resolve ALPHA to TAO (in case of degistation)
     * @param _user The user's address
     * @param _netuid The subnet ID
     * @param _taoAmount The amount of TAO to add to user's balance
     */
    function resolveAlpha(address _user, uint16 _netuid, uint256 _taoAmount)
        external onlyManager nonReentrant
    {
        require(!activeSubnets[_netuid], "subnet enabled");
        require(_lowAlphaInPool(_netuid), "high alpha");

        require(_user != address(0), "zero address");
        require(_netuid > 0, "bad netuid");
        require(_taoAmount > 0, "zero amount");
        require(userAlphaBalance[_user][_netuid] > 0, "zero alpha");

        // update balances
        uint256 alphaAmount = userAlphaBalance[_user][_netuid];
        _decreaseSubnetAlphaBalance(_netuid, alphaAmount);

        // clear user all subnet alpha balance and add tao balance
        _decreaseUserAlphaBalance(_user, _netuid, alphaAmount);
        _increaseUserAlphaBalance(_user, 0, _taoAmount);

        // deregistered TAO returned to staking pool, so stake it
        uint256 addedStake = _addStake(_taoAmount, 0);
        _increaseSubnetAlphaBalance(0, addedStake);

        emit ResolveAlpha(msg.sender, _user, _netuid, alphaAmount, _taoAmount);
    }

    /**
     * @dev Get custom ALPHA price for a subnet
     * @param _netuid The subnet ID
     * @return The ALPHA price, decimal 9
     */
    function getAlphaPrice(uint16 _netuid) public view returns (uint256) {
        return alpha.simSwapAlphaForTao(_netuid, 1e9);
    }

    // Internal functions

    function _lowAlphaInPool(uint16 _netuid) internal view returns (bool) {
        if (_netuid == 0) {
            return false;
        }
        uint256 alphaInPool = alpha.getAlphaInPool(_netuid);
        uint256 alphaOutPool = alpha.getAlphaOutPool(_netuid);
        return alphaInPool < MIN_POOL_ALPHA_THRESHOLD && alphaOutPool < MIN_POOL_ALPHA_THRESHOLD;
    }

    function _highAlphaInPool(uint16 _netuid) internal view returns (bool) {
        if (_netuid == 0) {
            return true;
        }
        uint256 alphaInPool = alpha.getAlphaInPool(_netuid);
        uint256 alphaOutPool = alpha.getAlphaOutPool(_netuid);
        return alphaInPool > MIN_POOL_ALPHA_THRESHOLD && alphaOutPool > MIN_POOL_ALPHA_THRESHOLD;
    }

    function _settleLoanRepayment(
        LoanData storage _loanData
    ) internal returns (uint256 repayAmount, uint256 protocolFee) {
        (repayAmount, protocolFee) = _calculateRepayAmount(_loanData);
        _chargeFee(protocolFee);
        _updateLenderRepayBalance(_loanData, repayAmount - protocolFee);
        _updateLoanData(_loanData, STATE.REPAID);
    }

    function _requireLoanActive(LoanData storage _loanData) internal view {
        require(_loanData.state == STATE.OPEN || _loanData.state == STATE.IN_COLLECTION, "loan inactive");
    }

    function _requireSubnetActive(uint16 _netuid) view internal {
        require(activeSubnets[_netuid] && _highAlphaInPool(_netuid), "subnet inactive");
    }

    function _getLoanData(uint256 _loanId) internal view returns (LoanTerm storage, LoanData storage, Offer memory) {
        LoanTerm storage loanTerm = loanTerms[_loanId];
        return (loanTerm, loanRecords[loanTerm.loanDataId], loanOffers[loanRecords[loanTerm.loanDataId].offerId]);
    }

    function _lenderBalanceChecker(Offer memory _offer, uint256 _taoAmount) internal view {
        require(userAlphaBalance[_offer.lender][0] >= _taoAmount, "low lender tao");
        require(userLendBalance[_offer.lender][_offer.offerId] + _taoAmount <= _offer.maxTaoAmount, "exceeds max");
    }

    function _alphaPriceChecker(Offer memory _offer, uint256 _taoAmount, uint256 _alphaAmount) internal view {
        uint256 alphaPrice = getAlphaPrice(_offer.netuid);
        require(_offer.maxAlphaPrice * RATE_BASE < alphaPrice * SAFE_ALPHA_PRICE, "bad price");
        require(_alphaAmount * _offer.maxAlphaPrice >= _taoAmount * PRICE_BASE, "low collateral");
    }

    function _simAlphaPriceChecker(Offer memory _offer, uint256 _taoAmount, uint256 _alphaAmount, uint256 _alphaPrice) internal pure {
        require(_offer.maxAlphaPrice * RATE_BASE < _alphaPrice * SAFE_ALPHA_PRICE, "bad price");
        require(_alphaAmount * _offer.maxAlphaPrice >= _taoAmount * PRICE_BASE, "low collateral");
    }

    function _calculateRepayAmount(LoanData storage _loanData) internal view returns (uint256, uint256) {
        Offer memory offer = loanOffers[_loanData.offerId];
        uint256 elapsedBlocks = block.number - _loanData.startBlock;
        uint256 interest = (_loanData.loanAmount * elapsedBlocks * offer.dailyInterestRate) / (BLOCKS_PER_DAY * PRICE_BASE);
        uint256 repayAmount = _loanData.loanAmount + interest;
        uint256 protocolFee = interest * FEE_RATE / RATE_BASE;

        return (repayAmount, protocolFee);
    }

    function _updateLenderBorrowBalance(Offer memory _offer, uint256 _taoAmount) internal {
        userAlphaBalance[_offer.lender][0] -= _taoAmount;
        userLendBalance[_offer.lender][_offer.offerId] += _taoAmount;
    }

    function _updateLenderRepayBalance(LoanData storage _loanData, uint256 _repayment) internal {
        Offer memory offer = loanOffers[_loanData.offerId];
        userAlphaBalance[offer.lender][0] += _repayment;
        if (_repayment > 0) {
            userLendBalance[offer.lender][offer.offerId] -= _loanData.loanAmount;
        }
    }

    function _newLoanData(uint256 _loanId, Offer memory _offer, uint256 _newLoanAmount) internal returns (uint256) {
        uint256 loanDataId = nextLoanDataId;
        nextLoanDataId++;

        loanOffers[_offer.offerId] = _offer;
        LoanData memory newLoanData = LoanData({
            loanId: _loanId,
            offerId: _offer.offerId,
            startBlock: block.number,
            loanAmount: _newLoanAmount,
            initiator: msg.sender,
            state: STATE.OPEN,
            lastUpdateBlock: block.number
        });
        loanRecords[loanDataId] = newLoanData;

        return loanDataId;
    }

    function _newLoan(Offer memory _offer, uint256 _taoAmount, uint256 _alphaAmount) internal returns (uint256) {
        uint256 loanId = nextLoanId;
        nextLoanId++;

        uint256 loanDataId = _newLoanData(loanId, _offer, _taoAmount);
        LoanTerm memory loanTerm = LoanTerm({
            borrower: msg.sender,
            collateralAmount: _alphaAmount,
            netuid: _offer.netuid,
            loanDataId: loanDataId
        });
        loanTerms[loanId] = loanTerm;

        return loanId;
    }

    function _updateLoanData(LoanData storage _loanData, STATE _state) internal {
        _loanData.initiator = msg.sender;
        _loanData.state = _state;
        _loanData.lastUpdateBlock = block.number;
    }

    function _updateLoanTerm(LoanTerm storage _loanTerm, uint256 _loanDataId) internal {
        _loanTerm.loanDataId = _loanDataId;
    }

    function _chargeFee(uint256 _protocolFee) internal {
        protocolFeeAccumulated += _protocolFee;
    }

    function _decreaseFee(uint256 _protocolFee) internal {
        protocolFeeAccumulated -= _protocolFee;
    }

    function _increaseUserAlphaBalance(address _user, uint16 _netuid, uint256 _alphaAmount) internal {
        userAlphaBalance[_user][_netuid] += _alphaAmount;
    }

    function _decreaseUserAlphaBalance(address _user, uint16 _netuid, uint256 _alphaAmount) internal {
        userAlphaBalance[_user][_netuid] -= _alphaAmount;
    }

    function _increaseSubnetAlphaBalance(uint16 _netuid, uint256 _alphaAmount) internal {
        subnetAlphaBalance[_netuid] += _alphaAmount;
    }

    function _decreaseSubnetAlphaBalance(uint16 _netuid, uint256 _alphaAmount) internal {
        subnetAlphaBalance[_netuid] -= _alphaAmount;
    }

    function _transferTao(address _to, uint256 _amountRao) internal {
        payable(_to).transfer(_amountRao * 1e9); // Convert RAO to EVM TAO
    }

    function _depositAlpha(uint16 _netuid, uint256 _amount, bytes32 _delegateHotkey) internal returns (uint256) {
        uint256 beforeStake = _getContractStake(_netuid);

        bytes memory transferData = abi.encodeWithSelector(
            IStaking.transferStake.selector,
            CONTRACT_COLDKEY,
            _delegateHotkey,
            _netuid,
            _netuid,
            _amount
        );
        (bool transferSuccess, ) = address(staking).delegatecall(transferData);
        require(transferSuccess, "transfer failed");

        if (_delegateHotkey != DELEGATE_HOTKEY) {
            bytes memory moveData = abi.encodeWithSelector(
                IStaking.moveStake.selector,
                _delegateHotkey,
                DELEGATE_HOTKEY,
                _netuid,
                _netuid,
                _amount
            );
            (bool moveSuccess, ) = address(staking).call(moveData);
            require(moveSuccess, "move failed");
        }

        uint256 afterStake = _getContractStake(_netuid);
        require(afterStake > beforeStake, "insufficient deposit");

        return afterStake - beforeStake;
    }

    function _withdrawAlpha(uint16 _netuid, uint256 _amount, bytes32 _userColdkey) internal {
        uint256 beforeStake = _getContractStake(_netuid);
        require(beforeStake >= _amount, "low stake");

        bytes memory data = abi.encodeWithSelector(
            IStaking.transferStake.selector,
            _userColdkey,
            DELEGATE_HOTKEY,
            _netuid,
            _netuid,
            _amount
        );
        (bool success, ) = address(staking).call(data);
        require(success, "transfer failed");

        uint256 afterStake = _getContractStake(_netuid);
        require(afterStake >= beforeStake - _amount, "insufficient deposit");
    }

    function _addStake(uint256 _amountRao, uint16 _netuid) internal returns (uint256) {
        uint256 beforeStake = _getContractStake(_netuid);

        bytes memory data = abi.encodeWithSelector(
            IStaking.addStake.selector,
            DELEGATE_HOTKEY,
            _amountRao,
            _netuid
        );
        (bool success, ) = address(staking).call(data);
        require(success, "add stake failed");

        uint256 afterStake = _getContractStake(_netuid);
        require(afterStake > beforeStake, "insufficient buy alpha");

        return afterStake - beforeStake;
    }

    function _removeStake(uint256 _amountRao, uint16 _netuid) internal returns (uint256) {
        uint256 beforeRemove = address(this).balance / 1e9;

        bytes memory data = abi.encodeWithSelector(
            IStaking.removeStake.selector,
            DELEGATE_HOTKEY,
            _amountRao,
            _netuid
        );
        (bool success, ) = address(staking).call(data);
        require(success, "remove stake failed");

        uint256 afterRemove = address(this).balance / 1e9;
        require(afterRemove > beforeRemove, "insufficient sell tao");

        return afterRemove - beforeRemove;
    }

    function _getContractStake(uint16 netuid) internal view returns (uint256) {
        return
            staking.getStake(
                DELEGATE_HOTKEY,
                CONTRACT_COLDKEY,
                netuid
            );
    }

    receive() external payable {}
    fallback() external payable {}

    /**
     * @dev Storage gap for future upgrades
     * Reserve 49 slots to prevent storage collisions in future contract versions
     * (50 - 1 for subnetMaxLevels mapping added in v2)
     * When adding new state variables in upgrades, reduce this gap accordingly
     */
    uint256[49] private __gap;
}


