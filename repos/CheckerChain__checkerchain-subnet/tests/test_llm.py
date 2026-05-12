import asyncio
from checkerchain.miner.forward import get_overall_score
from checkerchain.miner.llm import generate_review_score
from checkerchain.types.checker_chain import (
    Category,
    CreatedBy,
    Operation,
    UnreviewedProduct,
)


if __name__ == "__main__":
    product = UnreviewedProduct(
        "asdfljk",
        "Celo",
        1,
        Category("asdfjkl", "Blockchain & Crypto"),
        "Celo is a blockchain platform focused on mobile-first decentralized finance (DeFi) solutions and financial inclusion. \n\nIt was founded in 2017 by Rene Reinsberg, Marek Olszewski, and Sep Kamvar. Celo is headquartered in San Francisco, USA, and operates as an open-source platform supporting global accessibility and financial empowerment.",
        "forum.celo.org",
        "USA",
        Operation(True, "asdkjfk", []),
        "",
        "",
        "0",
        ["Defi", "Web3"],
        "celo",
        [],
        [],
        "https://x.com/celo",
        False,
        False,
        "elrond",
        CreatedBy(
            "asdfjkl",
            "erd1nznndfle036nfeqm4q7kuvswwlpfwre8myxkdgjs5exdw57473uqydymat",
            "piyushburlakoti",
            89.62,
            "Interested in crypto",
            "Piyush Burlakoti",
            "/images/users/1734097153445.webp",
        ),
        [],
        "published",
        1741533261645,
        [],
        "2025-03-08T15:13:45.673Z",
        "2025-03-08T23:16:45.442Z",
        0,
        "/images/products/1741446826191.jpg",
        "/images/products/1741446826414.jpg",
        19,
        0,
        "67cc5ea9040c09b84a280c9a",
        0,
        False,
    )
    review_by_llm = asyncio.run(generate_review_score(product))
    print(review_by_llm)
    overall_score = get_overall_score(review_by_llm)
    print("overall score: {}", overall_score)
