"""Seed companies. All fictional: add real startups through /admin with verified public facts.

`demo_bias` is not stored. It only shapes the fake crowd produced by "Load demo votes": positive means
the demo room overrates the pitch, negative means it underrates it.

Evidence factors are 0-5; leave one out (or None) when it's unknown.
"""

COMPANIES = [
    {
        # Designed demo case: polished pitch, weak fundamentals.
        "name": "TideLedger",
        "sector": "ocean plastics",
        "one_liner": "AI and blockchain marketplace that turns recovered ocean plastic into tradeable credits.",
        "claim_ask": "Raising €3M seed to launch in 40 countries next year.",
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
        "sector": "aquaculture & feed",
        "one_liner": "Dries Baltic seaweed into a feed supplement for dairy cows.",
        "claim_ask": "Raising €800k to double drying capacity at its coastal plant.",
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
        "sector": "desalination",
        "one_liner": "Floating solar-powered desalination units for island communities.",
        "claim_ask": "Raising €500k to scale its floating desalination pilot.",
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
        "sector": "aquaculture",
        "one_liner": "Farms mussels in the Archipelago Sea to pull nitrogen out of the water and sells nutrient credits.",
        "claim_ask": "Seeking €1.2M blended finance for three new farm lines.",
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
        "sector": "maritime robotics",
        "one_liner": "Hull-cleaning robot that scrubs ships in port without a dry dock.",
        "claim_ask": "Raising €2M Series A after five port pilots.",
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
        "sector": "wave energy",
        "one_liner": "Tiny wave-energy buoys that power ocean sensors forever.",
        "claim_ask": "Raising €1M pre-seed to reach a sea-trial prototype.",
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
        "sector": "media (allegedly)",
        "one_liner": "A social media agency that runs Instagram accounts for individual fish.",
        "claim_ask": "Raising €2M to sign 10,000 fish to exclusive content deals.",
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
        "sector": "fintech (fisheries)",
        "one_liner": "Tokenised squid futures so anyone can bet on next year's catch.",
        "claim_ask": "Raising €5M through its own token sale.",
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
        "sector": "marine tourism",
        "one_liner": "Underwater co-working pods anchored in the Baltic, Wi-Fi included.",
        "claim_ask": "Raising €4M to build the first 12-desk pod off the coast.",
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
        "sector": "maritime sensors",
        "one_liner": "Ice-load sensors that tell archipelago ferries where it's safe to break ice.",
        "claim_ask": "Raising €600k to expand from 4 to 20 ferries.",
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
        "sector": "marine fuels",
        "one_liner": "Algae biofuel that will replace marine diesel by 2030.",
        "claim_ask": "Raising €10M to build a demonstration bio-refinery.",
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
        "sector": "shipping software",
        "one_liner": "Route-planning software that cuts fuel use for short-sea shipping.",
        "claim_ask": "Raising €1.5M seed to open a sales office in Hamburg.",
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
    ("JunctionX live", "live", ["TideLedger", "Fishfluencer", "Rakko Feed", "FrostWatch", "BrineWorks"], None),
]

DEMO_BIAS = {c["name"]: c["demo_bias"] for c in COMPANIES}
