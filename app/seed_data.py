"""Seed companies. All fictional: add real startups through /admin with verified public facts.

`demo_bias` is not stored. It only shapes the fake crowd produced by "Load demo votes": positive means
the demo room overrates the pitch, negative means it underrates it.

Evidence factors are 0-5; leave one out (or None) when it's unknown. `checklist` answers rungs of the readiness
ladders in rubric.json ("business.6" = BRL rung 6), each with the quote it rests on; unanswered rungs are unknown.
"""


def _deck(answer: str, quote: str) -> dict:
    """A checklist answer quoted from the company's own deck (the card's facts)."""
    return {"answer": answer, "quote": quote, "source": "deck"}


def _rungs(ladder: str, answers: dict) -> dict:
    return {f"{ladder}.{n}": a for n, a in answers.items()}


COMPANIES = [
    {
        # Designed demo case: polished pitch, weak fundamentals.
        "name": "TideLedger",
        "emoji": "🧴",
        "sector": "ocean plastics",
        "one_liner": "Pick up a bottle on the beach, scan it, earn a token.",
        "claim_ask": "€3M to launch in 40 countries next year",
        "facts": [
            {"label": "Team", "value": "2 founders, no engineers yet"},
            {"label": "Traction", "value": "Waitlist of 1,200, no paying customers, no plastic collected"},
        ],
        "evidence": {
            "trl_stage": "concept", "patents": 0,
            "impact": {"problem_pressure": 4.5, "solution_potential": 1.5},
            "brl": {"market": 2, "value_prop": 2, "business_model": 1},
            "redstone": {"market": 3, "product": 1, "team": 1.5, "business_model": 1, "competition": 2,
                         "marketing": 3, "financials": 0.5, "tech": 1.5, "deal_dynamics": 1, "impact": 2},
            # BRL 2: the concept is clear, but nothing shows a business model or a quantified market yet.
            "checklist": _rungs("business", {
                1: _deck("yes", "Pick up a bottle on the beach, scan it, earn a token."),
                2: _deck("yes", "Pick up a bottle on the beach, scan it, earn a token."),
                5: _deck("no", "Waitlist of 1,200, no paying customers, no plastic collected"),
                6: _deck("no", "no paying customers"),
            }) | _rungs("tech", {
                1: _deck("yes", "Pick up a bottle on the beach, scan it, earn a token."),
                2: _deck("yes", "Pick up a bottle on the beach, scan it, earn a token."),
                3: _deck("no", "2 founders, no engineers yet"),
            }),
        },
        "evidence_note": "Demo case: strong narrative, no product, no collection partners, valuation ask out of line.",
        "demo_bias": 1.7,
        "opportunities": [
            {"kind": "partner", "name": "A municipal waste operator", "fit": 0.8, "stage_fit": "pre-seed",
             "why": "Proves plastic can actually be collected and verified before any marketplace exists."},
            {"kind": "grant", "name": "Business Finland Tempo", "fit": 0.6, "stage_fit": "pre-seed",
             "why": "Small non-dilutive money to test the collection model, not the token."},
            {"kind": "investor", "name": "Climate-focused angel syndicate", "fit": 0.3, "stage_fit": "pre-seed",
             "why": "Only after a working pilot; a €3M seed is not credible today."},
        ],
    },
    {
        # Designed demo case: diamond in the rough.
        "name": "Rakko Feed",
        "emoji": "🐄",
        "sector": "aquaculture & feed",
        "one_liner": "Dried Baltic seaweed in cow feed. The cows burp less methane.",
        "claim_ask": "€800k to double its drying plant",
        "facts": [
            {"label": "Revenue", "value": "€420k last year; 3 dairy co-ops buying repeatedly"},
            {"label": "Evidence", "value": "Two university feeding trials: 12–18% less methane per cow"},
        ],
        "evidence": {
            "trl_stage": "deployed", "patents": 1,
            "impact": {"measurability": 4.5, "problem_pressure": 4.5, "solution_potential": 4.5},
            "brl": {"market": 4, "value_prop": 4.5, "business_model": 4.5, "scalability": 3.5},
            "redstone": {"market": 4, "product": 4, "team": 4, "business_model": 4.5, "competition": 4,
                         "marketing": 3, "financials": 4, "tech": 3.5, "deal_dynamics": 4, "impact": 4.5},
            # BRL 8 and TRL 8: repeat paying customers and peer-reviewed trials; scaling is what the raise is for.
            "checklist": _rungs("business", {
                1: _deck("yes", "Dried Baltic seaweed in cow feed. The cows burp less methane."),
                2: _deck("yes", "Dried Baltic seaweed in cow feed. The cows burp less methane."),
                **{n: _deck("yes", "€420k last year; 3 dairy co-ops buying repeatedly") for n in range(3, 9)},
            }) | _rungs("tech", {
                **{n: _deck("yes", "Two university feeding trials: 12–18% less methane per cow") for n in range(1, 7)},
                7: _deck("yes", "€420k last year; 3 dairy co-ops buying repeatedly"),
                8: _deck("yes", "€420k last year; 3 dairy co-ops buying repeatedly"),
            }),
        },
        "evidence_note": "Demo case: boring one-liner, real revenue, peer-reviewed trials, sensible ask.",
        "demo_bias": -1.4,
        "opportunities": [
            {"kind": "investor", "name": "Redstone", "fit": 0.85, "stage_fit": "seed",
             "why": "Revenue-backed seed with measurable climate impact; fits an impact-aware VC."},
            {"kind": "grant", "name": "EU BlueInvest", "fit": 0.8, "stage_fit": "seed",
             "why": "Blue-economy scale-up support and investor matchmaking for exactly this stage."},
            {"kind": "customer", "name": "Nordic dairy co-operatives", "fit": 0.7, "stage_fit": "seed",
             "why": "Existing buyers: a multi-year offtake makes the capacity raise low-risk."},
        ],
    },
    {
        "name": "BrineWorks",
        "emoji": "🚰",
        "sector": "desalination",
        "one_liner": "A solar raft that turns seawater into drinking water for island villages.",
        "claim_ask": "€500k to build ten more rafts",
        "facts": [
            {"label": "Pilot", "value": "1 unit running 9 months in the archipelago"},
            {"label": "Team", "value": "6 people, including 2 water engineers"},
        ],
        "evidence": {
            "trl_stage": "pilot", "patents": 0,
            "impact": {"measurability": 3.5, "problem_pressure": 3.5, "solution_potential": 3.5},
            "brl": {"market": 3, "value_prop": 3.5, "business_model": 2.5},
            "redstone": {"market": 3, "product": 3, "team": 3.5, "business_model": 2.5, "competition": 3,
                         "tech": 3, "deal_dynamics": 3, "impact": 3.5},
        },
        "evidence_note": "Solid pilot; unit economics and financials not disclosed.",
        "demo_bias": 0.3,
        "opportunities": [
            {"kind": "grant", "name": "Business Finland", "fit": 0.75, "stage_fit": "seed",
             "why": "Pilot-to-product funding fits a single running unit."},
            {"kind": "partner", "name": "Island municipalities in the archipelago", "fit": 0.7, "stage_fit": "seed",
             "why": "Second and third deployments prove the economics."},
            {"kind": "investor", "name": "Nordic water-tech angels", "fit": 0.5, "stage_fit": "seed",
             "why": "Small ticket matches the €500k ask."},
        ],
    },
    {
        "name": "Simpukka Farms",
        "emoji": "🦪",
        "sector": "aquaculture",
        "one_liner": "Mussel farms that soak up fertiliser runoff from the sea.",
        "claim_ask": "€1.2M for three more farm lines",
        "facts": [
            {"label": "Pilot", "value": "2 farm lines, 40 t harvested"},
            {"label": "Revenue", "value": "€60k from mussel-meal sales; credits not yet sold"},
        ],
        "evidence": {
            "trl_stage": "demonstrated", "patents": 0,
            "impact": {"measurability": 4, "problem_pressure": 4.5, "solution_potential": 3.5},
            "brl": {"market": 2.5, "value_prop": 3.5, "business_model": 2.5, "scalability": 2.5},
            "redstone": {"market": 2.5, "product": 3.5, "team": 3.5, "business_model": 2.5, "competition": 3,
                         "marketing": 2, "financials": 2, "tech": 3, "deal_dynamics": 3, "impact": 4.5},
        },
        "evidence_note": "Strong impact, credit market unproven.",
        "demo_bias": 0.0,
        "opportunities": [
            {"kind": "grant", "name": "EMFAF (EU fisheries & aquaculture fund)", "fit": 0.8, "stage_fit": "seed",
             "why": "Aquaculture-specific co-funding suits farm-line capex."},
            {"kind": "partner", "name": "Regional water-protection programme", "fit": 0.7, "stage_fit": "seed",
             "why": "A first nutrient-credit buyer validates the second revenue line."},
        ],
    },
    {
        "name": "Barnacle Buster",
        "emoji": "🤖",
        "sector": "maritime robotics",
        "one_liner": "A robot that scrubs ship hulls while they sit in port.",
        "claim_ask": "€2M after five port pilots",
        "facts": [
            {"label": "Customers", "value": "2 ferry operators on paid trials"},
            {"label": "Permits", "value": "In-water cleaning permit in 2 ports"},
        ],
        "evidence": {
            "trl_stage": "demonstrated", "patents": 2,
            "impact": {"measurability": 3.5, "problem_pressure": 3.5, "solution_potential": 3.5},
            "brl": {"market": 3.5, "value_prop": 4, "business_model": 3.5, "scalability": 3},
            "redstone": {"market": 3.5, "product": 3.5, "team": 3.5, "business_model": 3.5, "competition": 2.5,
                         "marketing": 3, "financials": 3, "tech": 4, "deal_dynamics": 3, "impact": 3},
        },
        "evidence_note": "Crowded space; permits are the moat.",
        "demo_bias": -0.2,
        "opportunities": [
            {"kind": "customer", "name": "Baltic ferry operators", "fit": 0.8, "stage_fit": "A",
             "why": "Convert paid trials into fleet contracts before the A."},
            {"kind": "grant", "name": "EIC Accelerator", "fit": 0.6, "stage_fit": "A",
             "why": "Deep-tech robotics with commercial pull."},
        ],
    },
    {
        "name": "WaveWhisper",
        "emoji": "🛟",
        "sector": "wave energy",
        "one_liner": "A buoy the size of a football that charges ocean sensors with waves.",
        "claim_ask": "€1M to put the first one in the sea",
        "facts": [
            {"label": "Stage", "value": "Tank-tested at 1:20 scale"},
            {"label": "Team", "value": "3 PhDs, no commercial hire"},
        ],
        "evidence": {
            "trl_stage": "lab", "patents": 1,
            "impact": {"problem_pressure": 3, "solution_potential": 3},
            "brl": {"market": 2.5, "value_prop": 3, "business_model": 1.5},
            "redstone": {"market": 2.5, "product": 2, "team": 3, "competition": 3.5, "tech": 3.5,
                         "deal_dynamics": 2.5},
        },
        "evidence_note": "Credible science, no commercial evidence. Many factors unknown.",
        "demo_bias": 0.8,
        "opportunities": [
            {"kind": "grant", "name": "Horizon Europe (Mission Ocean)", "fit": 0.75, "stage_fit": "pre-seed",
             "why": "Research-to-sea-trial money suits a lab-stage device."},
            {"kind": "partner", "name": "An ocean-sensor manufacturer", "fit": 0.6, "stage_fit": "pre-seed",
             "why": "A design partner turns 'forever' into a spec with a buyer."},
        ],
    },
    {
        "name": "Fishfluencer",
        "emoji": "🤳",
        "sector": "media (allegedly)",
        "one_liner": "Instagram accounts, run on behalf of individual fish.",
        "claim_ask": "€2M to sign 10,000 fish",
        "facts": [
            {"label": "Traction", "value": "3 accounts, 41 followers in total"},
            {"label": "Revenue", "value": "€0"},
        ],
        "evidence": {
            "trl_stage": "idea", "patents": 0,
            "impact": {"measurability": 0.5, "problem_pressure": 0, "solution_potential": 0.5},
            "brl": {"market": 0.5, "value_prop": 0.5, "business_model": 0.5, "scalability": 1},
            "redstone": {"market": 0.5, "product": 0.5, "team": 1, "business_model": 0.5, "competition": 2.5,
                         "marketing": 2, "financials": 0, "tech": 0.5, "deal_dynamics": 0.5, "impact": 0},
        },
        "evidence_note": "Joke company.",
        "demo_bias": 0.4,
        "opportunities": [
            {"kind": "partner", "name": "A public aquarium", "fit": 0.3, "stage_fit": "pre-seed",
             "why": "At least the fish would be real."},
        ],
    },
    {
        "name": "Krakenomics",
        "emoji": "🦑",
        "sector": "fintech (fisheries)",
        "one_liner": "Bet on next year's squid catch with a crypto token.",
        "claim_ask": "€5M through its own token sale",
        "facts": [
            {"label": "Regulation", "value": "No licence applied for"},
            {"label": "Team", "value": "Anonymous"},
        ],
        "evidence": {
            "trl_stage": "concept", "patents": 0,
            "impact": {"measurability": 0.5, "problem_pressure": 1, "solution_potential": 0.5},
            "brl": {"market": 1, "value_prop": 1, "business_model": 1},
            "redstone": {"market": 1.5, "product": 1, "team": 0, "business_model": 1, "competition": 2,
                         "marketing": 2, "financials": 0.5, "tech": 1.5, "deal_dynamics": 0, "impact": 0},
        },
        "evidence_note": "Joke company.",
        "demo_bias": 0.3,
        "opportunities": [
            {"kind": "partner", "name": "A financial regulator", "fit": 0.2, "stage_fit": "pre-seed",
             "why": "They will be in touch either way."},
        ],
    },
    {
        "name": "SeaSpa Pods",
        "emoji": "🫧",
        "sector": "marine tourism",
        "one_liner": "Rent a desk in a glass pod on the Baltic seabed.",
        "claim_ask": "€4M to sink the first 12-desk pod",
        "facts": [
            {"label": "Prototype", "value": "Renders only"},
            {"label": "Permits", "value": "None applied for"},
        ],
        "evidence": {
            "trl_stage": "idea", "patents": 0,
            "impact": {"measurability": 0.5, "problem_pressure": 0.5, "solution_potential": 1},
            "brl": {"market": 1, "value_prop": 1.5, "business_model": 1},
            "redstone": {"market": 1, "product": 0.5, "team": 1.5, "business_model": 1, "competition": 3.5,
                         "marketing": 2.5, "financials": 0.5, "tech": 1, "deal_dynamics": 0.5, "impact": 0.5},
        },
        "evidence_note": "Joke company.",
        "demo_bias": 0.6,
        "opportunities": [
            {"kind": "partner", "name": "A marine construction firm", "fit": 0.3, "stage_fit": "pre-seed",
             "why": "Get a real cost estimate before anything else."},
        ],
    },
    {
        "name": "FrostWatch",
        "emoji": "🧊",
        "sector": "maritime sensors",
        "one_liner": "Sensors on ferry hulls that map where the ice is safe to break.",
        "claim_ask": "€600k to go from 4 ferries to 20",
        "facts": [
            {"label": "Deployed", "value": "4 ferries, 2 winters of data"},
            {"label": "Revenue", "value": "€150k annual recurring"},
        ],
        "evidence": {
            "trl_stage": "deployed", "patents": 1,
            "impact": {"measurability": 3.5, "problem_pressure": 3.5, "solution_potential": 3.5},
            "brl": {"market": 3, "value_prop": 4.5, "business_model": 4, "scalability": 3},
            "redstone": {"market": 3, "product": 4, "team": 4, "business_model": 4, "competition": 3.5,
                         "marketing": 3, "financials": 3.5, "tech": 4, "deal_dynamics": 3.5, "impact": 3},
        },
        "evidence_note": "Niche but real; paying customers.",
        "demo_bias": -0.9,
        "opportunities": [
            {"kind": "customer", "name": "Finnish and Swedish ferry operators", "fit": 0.85, "stage_fit": "seed",
             "why": "The 20-ferry target is a sales plan, not a research plan."},
            {"kind": "investor", "name": "Redstone", "fit": 0.6, "stage_fit": "seed",
             "why": "Small, revenue-backed round in a niche with clear buyers."},
        ],
    },
    {
        "name": "GreenGlug",
        "emoji": "🛢️",
        "sector": "marine fuels",
        "one_liner": "Ship fuel brewed from algae, replacing marine diesel by 2030.",
        "claim_ask": "€10M for a demonstration refinery",
        "facts": [
            {"label": "Cost", "value": "Lab batches at 50× the cost of marine diesel"},
            {"label": "Funding", "value": "€300k in grants to date"},
        ],
        "evidence": {
            "trl_stage": "lab", "patents": 1,
            "impact": {"measurability": 3, "problem_pressure": 4.5, "solution_potential": 2},
            "brl": {"market": 3.5, "value_prop": 2.5, "business_model": 1.5, "scalability": 1.5},
            "redstone": {"market": 3.5, "product": 1.5, "team": 2.5, "business_model": 1.5, "competition": 2,
                         "marketing": 2, "financials": 1, "tech": 2, "deal_dynamics": 1, "impact": 3},
        },
        "evidence_note": "Huge market, cost curve not credible yet.",
        "demo_bias": 1.0,
        "opportunities": [
            {"kind": "grant", "name": "Horizon Europe", "fit": 0.6, "stage_fit": "pre-seed",
             "why": "Research money to close the cost gap before any refinery."},
            {"kind": "partner", "name": "A shipping line's fuel R&D team", "fit": 0.5, "stage_fit": "pre-seed",
             "why": "A real buyer's cost target to work toward."},
        ],
    },
    {
        "name": "ShipShape Routing",
        "emoji": "🧭",
        "sector": "shipping software",
        "one_liner": "Software that plans a ship's route so it burns less fuel.",
        "claim_ask": "€1.5M to open a Hamburg sales office",
        "facts": [
            {"label": "Customers", "value": "7 paying operators"},
            {"label": "Results", "value": "6–9% fuel saving, audited by a classification society"},
        ],
        "evidence": {
            "trl_stage": "commercial", "patents": 0,
            "impact": {"measurability": 4, "problem_pressure": 4, "solution_potential": 3.5},
            "brl": {"market": 4, "value_prop": 4, "business_model": 4, "scalability": 4},
            "redstone": {"market": 4, "product": 4, "team": 3.5, "business_model": 4, "competition": 2.5,
                         "marketing": 3, "financials": 3.5, "tech": 3, "deal_dynamics": 3.5, "impact": 3.5},
        },
        "evidence_note": "Competitive category, but audited results and paying customers.",
        "demo_bias": -0.6,
        "opportunities": [
            {"kind": "investor", "name": "Redstone", "fit": 0.75, "stage_fit": "seed",
             "why": "SaaS with audited savings; classic seed profile."},
            {"kind": "grant", "name": "EU BlueInvest", "fit": 0.6, "stage_fit": "seed",
             "why": "Investor readiness and introductions for the Hamburg push."},
            {"kind": "customer", "name": "German short-sea operators", "fit": 0.7, "stage_fit": "seed",
             "why": "The office only makes sense with two signed pilots first."},
        ],
    },
]

# (label, mode, company names in order, days before seeding day)
DIVES = [
    ("#1", "daily", ["BrineWorks", "Fishfluencer", "FrostWatch", "GreenGlug", "Simpukka Farms"], 2),
    ("#2", "daily", ["Barnacle Buster", "Krakenomics", "ShipShape Routing", "WaveWhisper", "Rakko Feed"], 1),
    ("#3", "daily", ["TideLedger", "Rakko Feed", "SeaSpa Pods", "ShipShape Routing", "WaveWhisper"], 0),
    ("JunctionX final", "daily", ["TideLedger", "Fishfluencer", "Rakko Feed", "FrostWatch", "BrineWorks"], None),
]

DEMO_BIAS = {c["name"]: c["demo_bias"] for c in COMPANIES}

# The profile on each sample card: the vision behind "Read more", stages passed, money raised (euros, None when
# not disclosed) and investors. Fictional like the companies; the investor names are made up too.
PROFILES = {
    "TideLedger": {
        "vision": "Every bottle on a beach is a small deposit nobody has claimed. TideLedger wants to turn beach "
                  "clean-ups into a worldwide game: scan a bottle with your phone, prove you picked it up, and earn a "
                  "token that local shops and brands redeem. We believe a liquid market for collected plastic will pay "
                  "people to clean coastlines faster than any charity can. First 40 countries next year, then every coast.",
        "stages": ["Idea", "Friends and family round"],
        "raised_eur": 50000,
        "investors": [{"name": "Two family angels", "status": "invested", "amount_eur": 50000},
                      {"name": "Blockwave Ventures", "status": "interested", "amount_eur": None}],
    },
    "Rakko Feed": {
        "vision": "Cows are one of the biggest sources of methane on the planet, and the Baltic grows more seaweed than "
                  "anyone uses. Rakko Feed dries red seaweed harvested off the Finnish coast and mixes it into everyday "
                  "cattle feed. In two university trials, cows on our feed burped 12-18% less methane without eating less "
                  "or giving less milk. Three dairy co-ops already buy every month. Next: double the drying plant and "
                  "reach every Nordic co-op.",
        "stages": ["University spin-off", "Incubator programme", "Seed"],
        "raised_eur": 650000,
        "investors": [{"name": "Lumi Seed Fund", "status": "invested", "amount_eur": 400000},
                      {"name": "Kantele Angels", "status": "invested", "amount_eur": 250000},
                      {"name": "Green Herd Capital", "status": "interested", "amount_eur": None}],
    },
    "BrineWorks": {
        "vision": "Small islands live on shipped and bottled water that costs a fortune and burns diesel to deliver. "
                  "BrineWorks builds solar rafts that float off the shore and turn seawater into drinking water for a "
                  "village of a few hundred people, with no grid and no fuel. One raft has run for nine months in the "
                  "archipelago. Ten more will prove the economics through a season of storms, ice and summer peaks.",
        "stages": ["Pre-seed", "Municipal pilot"],
        "raised_eur": 300000,
        "investors": [{"name": "Skerry Impact Angels", "status": "invested", "amount_eur": 300000},
                      {"name": "Brackish Ventures", "status": "interested", "amount_eur": None}],
    },
    "Simpukka Farms": {
        "vision": "Farm runoff feeds the algae blooms that choke the Baltic every summer. Mussels filter that nitrogen "
                  "and phosphorus out of the water while they grow. Simpukka Farms runs mussel lines in nutrient-heavy "
                  "bays, sells the harvest as feed-grade mussel meal, and plans to sell verified nutrient-removal credits "
                  "to towns and farms. Two lines have harvested 40 tonnes; three more would make the first bay "
                  "measurably cleaner.",
        "stages": ["Pre-seed", "EU-funded pilot"],
        "raised_eur": 450000,
        "investors": [{"name": "Myrsky Blue Fund", "status": "invested", "amount_eur": 450000},
                      {"name": "Merikoski Family Office", "status": "interested", "amount_eur": None}],
    },
    "Barnacle Buster": {
        "vision": "A ship with a fouled hull can burn a tenth more fuel. Barnacle Buster is a robot that crawls over a "
                  "hull while the ship sits in port, scrubbing off growth before it hardens and catching the debris "
                  "instead of releasing it into the harbour. Two ferry operators are paying for trials, and we hold "
                  "in-water cleaning permits in two ports, which are hard to get. Five more port pilots, then cleaning "
                  "as a service, per vessel.",
        "stages": ["Seed", "Paid pilots"],
        "raised_eur": 1100000,
        "investors": [{"name": "Harbourline Capital", "status": "invested", "amount_eur": 800000},
                      {"name": "Kestrel Angels", "status": "invested", "amount_eur": 300000},
                      {"name": "Quayside Ventures", "status": "interested", "amount_eur": None}],
    },
    "WaveWhisper": {
        "vision": "Thousands of ocean sensors go dark every year because their batteries run out long before the "
                  "sensor does. WaveWhisper is a buoy the size of a football that turns small waves into a steady "
                  "trickle of power, so a sensor can stay out for years instead of months. The design has worked at "
                  "1:20 scale in a wave tank. Next is a full-size buoy at sea for one winter.",
        "stages": ["Research project", "Pre-seed grant"],
        "raised_eur": 150000,
        "investors": [{"name": "University innovation fund", "status": "invested", "amount_eur": 150000},
                      {"name": "Tidepool Seed Partners", "status": "interested", "amount_eur": None}],
    },
    "Fishfluencer": {
        "vision": "Fish are the most underrepresented creators on social media. Fishfluencer runs Instagram accounts "
                  "on behalf of individual fish, posting their daily lives, and will sell sponsorships to aquarium "
                  "brands. Our first three fish have 41 followers between them. With €2M we will sign 10,000 fish and "
                  "become the leading fish talent agency.",
        "stages": [],
        "raised_eur": 0,
        "investors": [],
    },
    "Krakenomics": {
        "vision": "Squid catches swing wildly from year to year, and nobody can bet on them. Krakenomics lets anyone "
                  "stake our token on next year's squid catch and win if they call it right. We will raise €5M in our "
                  "own token sale and open the market the day the token goes live.",
        "stages": [],
        "raised_eur": None,
        "investors": [],
    },
    "SeaSpa Pods": {
        "vision": "Remote work needs better views. SeaSpa Pods are glass coworking pods anchored on the Baltic seabed, "
                  "where you rent a desk and watch the fish while you answer email. The first pod will hold twelve "
                  "desks. The renders are done and we are ready to build.",
        "stages": [],
        "raised_eur": 0,
        "investors": [],
    },
    "FrostWatch": {
        "vision": "Icebreakers and winter ferries still guess where the ice is weakest. FrostWatch puts strain sensors "
                  "on ferry hulls, so every crossing measures the ice it breaks and adds to a live map of where it is "
                  "safe and cheap to pass. Four ferries have run it for two winters, and their operators pay €150k a "
                  "year for it. We want twenty ferries feeding the map by next winter.",
        "stages": ["Seed", "Two winters in commercial use"],
        "raised_eur": 900000,
        "investors": [{"name": "Polar Route Ventures", "status": "invested", "amount_eur": 600000},
                      {"name": "A ferry operator's venture arm", "status": "invested", "amount_eur": 300000}],
    },
    "GreenGlug": {
        "vision": "Shipping needs a fuel that works in today's engines and doesn't come out of the ground. GreenGlug "
                  "grows algae and turns it into a marine fuel meant to replace diesel by 2030. Our lab batches burn "
                  "cleanly in a test engine; they still cost about fifty times as much as diesel, and a demonstration "
                  "refinery is how we bring that cost down.",
        "stages": ["Lab research", "Public research grants"],
        "raised_eur": 300000,
        "investors": [{"name": "Public research grants", "status": "invested", "amount_eur": 300000},
                      {"name": "Seafuel Transition Fund", "status": "interested", "amount_eur": None}],
    },
    "ShipShape Routing": {
        "vision": "A ship that takes the right route at the right speed burns less fuel and still arrives on time. "
                  "ShipShape Routing plans voyages around weather, currents and port slots, and updates the plan as "
                  "conditions change. Seven operators pay for it today, and a classification society audited 6-9% "
                  "fuel savings on their ships. Now we want to sell to German shipping companies directly, from Hamburg.",
        "stages": ["Seed", "Series A in preparation"],
        "raised_eur": 2200000,
        "investors": [{"name": "Nordic SaaS Partners", "status": "invested", "amount_eur": 1500000},
                      {"name": "Kantele Angels", "status": "invested", "amount_eur": 700000},
                      {"name": "Elbe Maritime Ventures", "status": "interested", "amount_eur": None}],
    },
}
