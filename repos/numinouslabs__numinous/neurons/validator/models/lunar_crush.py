from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

LUNAR_CRUSH_COST_PER_CALL = Decimal("0.001")


class TopicTypesCount(BaseModel):
    model_config = ConfigDict(extra="allow")

    tweet: int = 0
    news: int = 0
    reddit_post: int = Field(0, alias="reddit-post")
    youtube_video: int = Field(0, alias="youtube-video")
    tiktok_video: int = Field(0, alias="tiktok-video")
    instagram_post: int = Field(0, alias="instagram-post")


class TopicTypesSentiment(BaseModel):
    model_config = ConfigDict(extra="allow")

    tweet: int | None = None
    news: int | None = None
    reddit_post: int | None = Field(None, alias="reddit-post")
    youtube_video: int | None = Field(None, alias="youtube-video")
    tiktok_video: int | None = Field(None, alias="tiktok-video")


class TopicData(BaseModel):
    model_config = ConfigDict(extra="allow")

    topic: str
    title: str
    topic_rank: int | None = None
    related_topics: list[str] = Field(default_factory=list)
    types_count: TopicTypesCount | None = None
    types_sentiment: TopicTypesSentiment | None = None
    interactions_24h: int | None = None
    num_contributors: int | None = None
    num_posts: int | None = None
    categories: list[str] = Field(default_factory=list)
    trend: str | None = None


class TopicConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str


class LunarCrushTopicResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: TopicConfig
    data: TopicData


class TimeSeriesDataPoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: int
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    sentiment: int | None = None
    galaxy_score: float | None = None
    alt_rank: int | None = None
    social_dominance: float | None = None
    contributors_active: int | None = None
    interactions: int | None = None
    posts_active: int | None = None
    posts_created: int | None = None


class TimeSeriesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    bucket: str | None = None
    topic: str | None = None
    name: str | None = None
    symbol: str | None = None
    generated: int | None = None


class LunarCrushTimeSeriesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: TimeSeriesConfig
    data: list[TimeSeriesDataPoint]


class NewsItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    post_type: str = "news"
    post_title: str | None = None
    post_description: str | None = None
    post_link: str | None = None
    post_created: int | None = None
    post_sentiment: float | None = None
    creator_name: str | None = None
    creator_display_name: str | None = None
    creator_followers: int | None = None
    interactions_24h: int | None = None


class LunarCrushNewsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: TopicConfig
    data: list[NewsItem]


class WhatsupTheme(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    description: str
    percent: float


class LunarCrushWhatsupResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: TopicConfig | dict = Field(default_factory=dict)
    summary: str
    supportive: list[WhatsupTheme] = Field(default_factory=list)
    critical: list[WhatsupTheme] = Field(default_factory=list)


class PostItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    post_type: str | None = None
    post_title: str | None = None
    post_link: str | None = None
    post_created: int | None = None
    post_sentiment: float | None = None
    creator_name: str | None = None
    creator_display_name: str | None = None
    creator_followers: int | None = None
    interactions_24h: int | None = None


class LunarCrushPostsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: TopicConfig
    data: list[PostItem]


class CoinData(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    symbol: str
    name: str
    price: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    market_cap_rank: int | None = None
    interactions_24h: int | None = None
    social_volume_24h: int | None = None
    social_dominance: float | None = None
    galaxy_score: float | None = None
    alt_rank: int | None = None
    sentiment: int | None = None
    percent_change_24h: float | None = None
    percent_change_7d: float | None = None


class CoinsListConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    sort: str | None = None
    total_rows: int | None = None


class LunarCrushCoinsListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    config: CoinsListConfig
    data: list[CoinData]


def calculate_cost() -> Decimal:
    return LUNAR_CRUSH_COST_PER_CALL
