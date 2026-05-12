// SPDX-License-Identifier: GPL-3.0

pragma solidity ^0.8.24;

import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

// Loan offer structure
struct Offer {
    bytes32 offerId;        // Offer ID
    address lender;         // Lender address
    uint16 netuid;          // Network ID
    uint256 nonce;          // Nonce for replay attack prevention
    uint256 expire;         // Expiration timestamp
    uint256 maxTaoAmount;   // Maximum loan amount
    uint256 maxAlphaPrice;  // Maximum ALPHA price accepted by lender for collateral calculation
    uint256 dailyInterestRate; // Daily interest rate (1e9 base, e.g. 10_000_000 = 1%)
    bytes signature;        // Signature of all above fields
}

// Loan Terms structure
struct LoanTerm {
    address borrower;       // Borrower address
    uint256 collateralAmount; // Alpha collateral amount
    uint16 netuid;          // Subnet ID
    uint256 loanDataId;
}

enum STATE {
    OPEN,
    IN_COLLECTION,
    REPAID,
    CLAIMED,
    RESOLVED
}

// Loan Data structure
struct LoanData {
    uint256 loanId;
    bytes32 offerId;
    uint256 startBlock;     // Loan start block number
    uint256 loanAmount;     // TAO loan amount (principal)
    address initiator;      // Initiator address (for transfer/refinance)
    STATE state;
    uint256 lastUpdateBlock; // Last operation block number
}

library LoanLib {
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    function verifySignature(
        bytes32 _message,
        bytes memory _signature,
        address _signer
    ) internal pure returns (bool) {
        bytes32 ethSignedMessageHash = _message.toEthSignedMessageHash();
        address recoveredSigner = ethSignedMessageHash.recover(_signature);
        return recoveredSigner == _signer;
    }

    /**
     * @dev Generate hash for loan offer according to EIP-712 standard
     * @param offer The loan offer struct (without signature field)
     * @return Hash of the loan offer
     */
    function calculateOfferId(Offer memory offer) internal pure returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                offer.lender,
                offer.netuid,
                offer.nonce,
                offer.expire,
                offer.maxTaoAmount,
                offer.maxAlphaPrice,
                offer.dailyInterestRate
            )
        );

        return keccak256(abi.encodePacked("\x19\x01", structHash));
    }

    /**
     * @dev Generate hash for loan offer according to EIP-712 standard
     * @param offer The loan offer struct (with signature field)
     * @return Hash of the loan offer
     */
    function calculateOfferHash(Offer memory offer) internal pure returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                offer.offerId,
                offer.lender,
                offer.netuid,
                offer.nonce,
                offer.expire,
                offer.maxTaoAmount,
                offer.maxAlphaPrice,
                offer.dailyInterestRate
            )
        );

        return keccak256(abi.encodePacked("\x19\x01", structHash));
    }

    /**
     * @dev Verify loan offer signature
     * @param offer The loan offer struct with signature
     * @return True if signature is valid
     */
    function verifyOfferSignature(Offer memory offer) internal pure returns (bool) {
        bytes32 offerHash = calculateOfferHash(offer);
        bytes32 ethSignedMessageHash = offerHash.toEthSignedMessageHash();
        (address recoveredSigner, ,) = ethSignedMessageHash.tryRecover(offer.signature);
        return recoveredSigner == offer.lender;
    }
}



