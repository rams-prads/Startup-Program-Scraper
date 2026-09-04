"""The programs we check on every run, and the domains we trust as sources.

The lists below are only a starting point. The model is told to correct a
name or a URL if a provider has moved things around, and to look for
programs that are not on the list at all.
"""

from urllib.parse import urlparse

# Checked on a quick refresh. The largest and most widely used programs.
CORE_PROGRAMS = [
    {"name": "NVIDIA Inception", "url": "https://www.nvidia.com/en-us/startups/"},
    {"name": "Nebius for Startups and AI Lift", "url": "https://nebius.com/startups"},
    {"name": "Together AI Startup Accelerator", "url": "https://www.together.ai/startups"},
    {"name": "Modal Startup Program", "url": "https://modal.com/startups"},
    {"name": "RunPod Startup Program", "url": "https://www.runpod.io/startup-program"},
    {"name": "Lambda GPU cloud startup credits", "url": "https://lambda.ai/service/gpu-cloud"},
    {"name": "AWS Activate", "url": "https://aws.amazon.com/activate/"},
    {"name": "Google for Startups Cloud Program", "url": "https://startup.google.com/programs/cloud/"},
    {"name": "Microsoft for Startups Founders Hub", "url": "https://startups.microsoft.com/"},
    {"name": "DigitalOcean Startups", "url": "https://www.digitalocean.com/startups"},
    {"name": "Oracle for Startups", "url": "https://www.oracle.com/cloud/oracle-for-startups/"},
    {"name": "E2E Networks Startup Program", "url": "https://www.e2enetworks.com/startup-program"},
]

# Added on a full refresh. Mid sized GPU clouds and the India based options.
EXTENDED_PROGRAMS = [
    {"name": "Cloudflare for Startups", "url": "https://www.cloudflare.com/startups/"},
    {"name": "Startup with IBM", "url": "https://www.ibm.com/products/startups"},
    {"name": "Vultr Digital Startup Program", "url": "https://www.vultr.com/programs/startups/"},
    {"name": "CoreWeave startup or accelerator program", "url": "https://www.coreweave.com/"},
    {"name": "Crusoe startup program", "url": "https://crusoe.ai/"},
    {"name": "Fal startup or grant program", "url": "https://fal.ai/"},
    {"name": "Replicate startup credits", "url": "https://replicate.com/"},
    {"name": "Baseten startup program", "url": "https://www.baseten.co/"},
    {"name": "Hugging Face compute grants or startup plan", "url": "https://huggingface.co/"},
    {"name": "Paperspace startup credits", "url": "https://www.paperspace.com/"},
    {"name": "Vast.ai startup or research credits", "url": "https://vast.ai/"},
    {"name": "Hyperstack startup program", "url": "https://www.hyperstack.cloud/"},
    {"name": "Scaleway Startup Program", "url": "https://www.scaleway.com/en/startup-program/"},
    {"name": "OVHcloud Startup Program", "url": "https://startup.ovhcloud.com/en/"},
    {"name": "Nscale startup program", "url": "https://www.nscale.com/"},
    {"name": "SambaNova startup or developer credits", "url": "https://sambanova.ai/"},
    {"name": "Cerebras startup or research access", "url": "https://www.cerebras.ai/"},
    {"name": "Groq startup or developer credits", "url": "https://groq.com/"},
    {"name": "Voltage Park startup or research credits", "url": "https://www.voltagepark.com/"},
    {"name": "Anthropic for Startups", "url": "https://www.anthropic.com/startups"},
    {"name": "OpenAI startup credits", "url": "https://openai.com/"},
    {"name": "Mistral AI for startups", "url": "https://mistral.ai/"},
    {"name": "Yotta Shakti Cloud startup program", "url": "https://shakticloud.ai/"},
    {"name": "Neysa startup program", "url": "https://www.neysa.ai/"},
    {"name": "JarvisLabs startup or research credits", "url": "https://jarvislabs.ai/"},
]

# Checked on a deep refresh. Adds the smaller GPU clouds, the inference
# providers, the regional clouds and the data platforms. Some of these have no
# startup program; those rows record that rather than being dropped.
DEEP_PROGRAMS = [
    # GPU clouds and neoclouds
    {"name": "Fluidstack", "url": "https://www.fluidstack.io/"},
    {"name": "DataCrunch", "url": "https://datacrunch.io/"},
    {"name": "Cudo Compute", "url": "https://www.cudocompute.com/"},
    {"name": "TensorDock", "url": "https://tensordock.com/"},
    {"name": "Massed Compute", "url": "https://massedcompute.com/"},
    {"name": "Genesis Cloud", "url": "https://www.genesiscloud.com/"},
    {"name": "Latitude.sh", "url": "https://www.latitude.sh/"},
    {"name": "Ori", "url": "https://www.ori.co/"},
    {"name": "Civo", "url": "https://www.civo.com/"},
    {"name": "Sesterce", "url": "https://www.sesterce.com/"},
    {"name": "Denvr Dataworks", "url": "https://www.denvrdata.com/"},
    {"name": "Shadeform", "url": "https://www.shadeform.ai/"},
    {"name": "Prime Intellect", "url": "https://www.primeintellect.ai/"},
    {"name": "SF Compute", "url": "https://sfcompute.com/"},
    {"name": "Thunder Compute", "url": "https://www.thundercompute.com/"},
    {"name": "Salad Cloud", "url": "https://salad.com/"},
    {"name": "io.net", "url": "https://io.net/"},
    {"name": "Akash Network", "url": "https://akash.network/"},
    {"name": "Hot Aisle", "url": "https://hotaisle.xyz/"},
    {"name": "Parasail", "url": "https://www.parasail.io/"},

    # Inference platforms and model APIs
    {"name": "Fireworks AI", "url": "https://fireworks.ai/"},
    {"name": "Anyscale", "url": "https://www.anyscale.com/"},
    {"name": "Deep Infra", "url": "https://deepinfra.com/"},
    {"name": "Novita AI", "url": "https://novita.ai/"},
    {"name": "Hyperbolic", "url": "https://hyperbolic.xyz/"},
    {"name": "Runware", "url": "https://runware.ai/"},
    {"name": "Beam Cloud", "url": "https://www.beam.cloud/"},
    {"name": "Cohere", "url": "https://cohere.com/"},
    {"name": "AI21 Labs", "url": "https://www.ai21.com/"},
    {"name": "Writer", "url": "https://writer.com/"},
    {"name": "Reka AI", "url": "https://www.reka.ai/"},
    {"name": "xAI", "url": "https://x.ai/"},
    {"name": "ElevenLabs Grants", "url": "https://elevenlabs.io/grants"},
    {"name": "AssemblyAI", "url": "https://www.assemblyai.com/"},
    {"name": "Deepgram Startup Program", "url": "https://deepgram.com/startups"},
    {"name": "OpenRouter", "url": "https://openrouter.ai/"},

    # Hyperscalers and regional clouds
    {"name": "Alibaba Cloud Startup Program", "url": "https://www.alibabacloud.com/"},
    {"name": "Tencent Cloud", "url": "https://www.tencentcloud.com/"},
    {"name": "Huawei Cloud Startup Program", "url": "https://www.huaweicloud.com/intl/en-us/"},
    {"name": "Akamai Linode", "url": "https://www.linode.com/"},
    {"name": "Hetzner Cloud", "url": "https://www.hetzner.com/cloud"},
    {"name": "Exoscale Startup Program", "url": "https://www.exoscale.com/startups/"},
    {"name": "UpCloud", "url": "https://upcloud.com/"},
    {"name": "Equinix Metal", "url": "https://deploy.equinix.com/"},

    # App platforms where the compute still costs money
    {"name": "Koyeb", "url": "https://www.koyeb.com/"},
    {"name": "Northflank", "url": "https://northflank.com/"},
    {"name": "Fly.io", "url": "https://fly.io/"},
    {"name": "Render", "url": "https://render.com/"},
    {"name": "Railway", "url": "https://railway.com/"},
    {"name": "Heroku for Startups", "url": "https://www.heroku.com/"},
    {"name": "Vercel for Startups", "url": "https://vercel.com/startups"},
    {"name": "Netlify for Startups", "url": "https://www.netlify.com/"},

    # Data and AI infrastructure
    {"name": "Pinecone", "url": "https://www.pinecone.io/"},
    {"name": "Weaviate", "url": "https://weaviate.io/"},
    {"name": "Qdrant", "url": "https://qdrant.tech/"},
    {"name": "Zilliz and Milvus", "url": "https://zilliz.com/"},
    {"name": "MongoDB for Startups", "url": "https://www.mongodb.com/startups"},
    {"name": "Neon", "url": "https://neon.com/"},
    {"name": "Supabase", "url": "https://supabase.com/"},
    {"name": "Redis", "url": "https://redis.io/"},
    {"name": "ClickHouse for Startups", "url": "https://clickhouse.com/"},
    {"name": "Snowflake Startup Program", "url": "https://www.snowflake.com/startups/"},
    {"name": "Databricks for Startups", "url": "https://www.databricks.com/company/startups"},
    {"name": "Confluent for Startups", "url": "https://www.confluent.io/"},
    {"name": "Elastic for Startups", "url": "https://www.elastic.co/"},
    {"name": "SingleStore", "url": "https://www.singlestore.com/"},
    {"name": "TigerData formerly Timescale", "url": "https://www.tigerdata.com/"},
    {"name": "Weights and Biases", "url": "https://wandb.ai/site/"},
    {"name": "Comet ML", "url": "https://www.comet.com/site/"},

    # Hardware and ecosystem programs
    {"name": "Intel Liftoff for AI Startups", "url": "https://www.intel.com/content/www/us/en/developer/programs/liftoff/overview.html"},
    {"name": "AMD developer and Instinct programs", "url": "https://www.amd.com/en/developer.html"},
    {"name": "Arm Flexible Access for Startups", "url": "https://www.arm.com/products/flexible-access"},
    {"name": "Qualcomm developer programs", "url": "https://www.qualcomm.com/developer"},
    {"name": "Cloudflare Workers Launchpad", "url": "https://www.cloudflare.com/launchpad/"},
    {"name": "GitHub for Startups", "url": "https://github.com/enterprise/startups"},

    # India and the wider region
    {"name": "Krutrim Cloud", "url": "https://olakrutrim.com/cloud"},
    {"name": "Tata Communications cloud", "url": "https://www.tatacommunications.com/"},
    {"name": "Sify Technologies cloud", "url": "https://www.sifytechnologies.com/"},
    {"name": "CtrlS", "url": "https://www.ctrls.in/"},
    {"name": "NxtGen Cloud", "url": "https://www.nxtgen.com/"},
    {"name": "Jio Cloud for business", "url": "https://www.jio.com/business/jio-cloud"},
    {"name": "Startup India recognised cloud benefits", "url": "https://www.startupindia.gov.in/"},
]


ALL_PROGRAMS = CORE_PROGRAMS + EXTENDED_PROGRAMS + DEEP_PROGRAMS

# A few official domains that do not show up in the seed URLs above but are
# still the provider talking about itself.
EXTRA_TRUSTED_DOMAINS = {
    "amazon.com",
    "microsoft.com",
    "azure.com",
    "google.com",
    "googleblog.com",
    "nvidia.com",
    "ovh.com",
    "ovhcloud.com",
    "digitalocean.com",
    "startupindia.gov.in",
}


def registrable_domain(url: str) -> str:
    """Rough second level domain for a URL.

    Good enough for the handful of hosts we care about. It does not try to
    be clever about things like co.uk because none of our sources use them.
    """
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def _seed_domains() -> set:
    domains = set(EXTRA_TRUSTED_DOMAINS)
    for program in ALL_PROGRAMS:
        domains.add(registrable_domain(program["url"]))
    domains.discard("")
    return domains


TRUSTED_DOMAINS = _seed_domains()


def classify_source(program_url: str, source_url: str) -> str:
    """Say how much we trust a source URL.

    "official"  the source sits on a provider domain we already know
    "own site"  the source sits on the same domain as the program page,
                which is what we want for a program we just discovered
    "third party" anything else, which we surface separately instead of
                trusting quietly
    """
    if not source_url:
        return "third party"

    source_domain = registrable_domain(source_url)
    if source_domain in TRUSTED_DOMAINS:
        return "official"
    if program_url and source_domain == registrable_domain(program_url):
        return "own site"
    return "third party"


SCOPES = {
    "quick": "the core programs, a few minutes",
    "full": "core plus the smaller providers",
    "deep": "everything we track, over a hundred",
}


def program_list(scope: str) -> list:
    """Programs to check for a given refresh scope."""
    if scope == "quick":
        return CORE_PROGRAMS
    if scope == "full":
        return CORE_PROGRAMS + EXTENDED_PROGRAMS
    return ALL_PROGRAMS
