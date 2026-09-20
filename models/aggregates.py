from enum import Enum
import json

class Categories(str, Enum):
    # News & Current Affairs
    politics = "politics"
    government = "government"
    law = "law"
    news = "news"
    world = "world"
    local = "local"
    crime = "crime"
    weather = "weather"
    disaster = "disaster"

    # Business & Economy
    business = "business"
    finance = "finance"
    investing = "investing"
    crypto = "crypto"
    markets = "markets"
    startups = "startups"
    economy = "economy"
    real_estate = "real_estate"
    jobs = "jobs"
    career = "career"

    # Tech & Science
    technology = "technology"
    gadgets = "gadgets"
    ai = "ai"
    software = "software"
    cybersecurity = "cybersecurity"
    science = "science"
    space = "space"
    environment = "environment"
    climate = "climate"

    # Health & Lifestyle
    health = "health"
    medicine = "medicine"
    nutrition = "nutrition"
    fitness = "fitness"
    wellness = "wellness"
    mental_health = "mental_health"
    parenting = "parenting"
    relationships = "relationships"
    lifestyle = "lifestyle"

    # Education & Learning
    education = "education"
    academic = "academic"
    learning = "learning"
    books = "books"
    languages = "languages"
    study = "study"
    

    # Entertainment & Culture
    entertainment = "entertainment"
    movies = "movies"
    tv = "tv"
    music = "music"
    art = "art"
    theater = "theater"
    celebrity = "celebrity"
    pop_culture = "pop_culture"

    # Sports
    sports = "sports"
    football = "football"
    basketball = "basketball"
    soccer = "soccer"
    tennis = "tennis"
    motorsports = "motorsports"
    esports = "esports"
    gaming = "gaming"

    # Other Interests
    travel = "travel"
    food = "food"
    cooking = "cooking"
    drinks = "drinks"
    fashion = "fashion"
    beauty = "beauty"
    home_garden = "home_garden"
    diy = "diy"
    automotive = "automotive"
    pets = "pets"
    animals = "animals"
    hobbies = "hobbies"
    photography = "photography"

    # Society
    religion = "religion"
    spirituality = "spirituality"
    social = "social"
    community = "community"
    activism = "activism"
    history = "history"




main_classification = [
    "news", "economy", "sci-tech", "health", "entertainment",
    "society", "interests", "education", "sports"
]

news = [
    "politics", "government", "law", "news", "world",
    "local", "crime", "weather", "disaster"
]

economy = [
    "business", "finance", "investing", "crypto", "markets",
    "startups", "economy", "real_estate", "jobs", "career"
]

sci_tech = [
    "technology", "gadgets", "ai", "software", "climate",
    "cybersecurity", "science", "space", "environment"
]

health = [
    "health", "medicine", "nutrition", "fitness", "wellness",
    "mental_health", "parenting", "relationships", "lifestyle"
]

entertainment = [
    "entertainment", "movies", "tv", "music", "art",
    "theater", "dance", "celebrity", "pop_culture"
]

society = [
    "religion", "spirituality", "social", "community",
    "activism", "history"
]

education = [
    "education", "academic", "learning", "books",
    "languages", "study"
]

sports = [
    "sports", "football", "basketball", "soccer", "tennis",
    "motorsports", "esports", "gaming"
]

interests = [
    "travel", "food", "cooking", "drinks", "fashion",
    "beauty", "home_garden", "diy", "automotive",
    "pets", "animals", "hobbies", "photography"
]


# Main classification prompt
AI_MESSAGE_1 = f"""
You are a post classification AI for a personalized content feed.

Analyze the following post:

<POST>
{{post_data}}
</POST>

Classify the post into exactly ONE of these main categories:
{main_classification}

Choose the category that best represents the primary subject
of the post, not merely a topic mentioned in passing.

Return ONLY the category name exactly as written in the list.
Do not include explanations, punctuation, or any other text.
""".strip()


# Main classification -> subcategory mapping
MAIN_CLASSIFICATIONS = {
    "news": news,
    "economy": economy,
    "sci-tech": sci_tech,
    "health": health,
    "entertainment": entertainment,
    "society": society,
    "interests": interests,
    "education": education,
    "sports": sports
}


# Generate the correlation scoring prompt
def create_annotation_prompt(post_data: str, category: str) -> str:
    categories = MAIN_CLASSIFICATIONS[category]

    return f"""
You are a content annotation AI for a personalized content feed.

Analyze the following post:

<POST>
{post_data}
</POST>

The post has been assigned to the main classification: {category}

Evaluate how strongly the post correlates with EACH of the
following subcategories:

{categories}

SCORING RULES:
- Assign a decimal score between 0.0 and 1.0 to every subcategory.
- 0.0 = completely unrelated to the post.
- 0.1-0.3 = weak or incidental relevance.
- 0.4-0.6 = moderate relevance.
- 0.7-0.9 = strong relevance.
- 1.0 = directly and strongly represents the subcategory.
- Evaluate each subcategory independently.
- Multiple subcategories may receive high scores.
- Do not assign a high score merely because a word appears.
  Consider the actual meaning and context of the post.
- A post may correlate with subcategories outside its main
  classification if they are genuinely relevant.
- Do not assign a score based on personal opinion or sentiment.

OUTPUT REQUIREMENTS:
Return ONLY a valid JSON object.
Include EVERY subcategory listed above as a key.
Every value must be a number between 0.0 and 1.0.
Do not include markdown, comments, or explanations.

Example format:
{json.dumps({key: 0.0 for key in categories})}
""".strip()


# Example usage
post_data = ""

# Step 1: Main classification
AI_MESSAGE_1 = AI_MESSAGE_1.format(post_data=post_data)

# Step 2: Generate subcategory prompt for the selected class
AI_MESSAGE_NEWS = create_annotation_prompt(post_data, "news")
AI_MESSAGE_ECONOMY = create_annotation_prompt(post_data, "economy")
AI_MESSAGE_SCI_TECH = create_annotation_prompt(post_data, "sci-tech")
AI_MESSAGE_HEALTH = create_annotation_prompt(post_data, "health")
AI_MESSAGE_ENTERTAINMENT = create_annotation_prompt(
    post_data, "entertainment"
)
AI_MESSAGE_SOCIETY = create_annotation_prompt(post_data, "society")
AI_MESSAGE_EDUCATION = create_annotation_prompt(post_data, "education")
AI_MESSAGE_SPORTS = create_annotation_prompt(post_data, "sports")
AI_MESSAGE_INTERESTS = create_annotation_prompt(post_data, "interests")