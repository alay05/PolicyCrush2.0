from sources.news.cms import fetch_cms_articles
from sources.news.crs import fetch_crs_articles
from sources.news.congress import fetch_congress_articles
from sources.news.fda import fetch_fda_articles
from sources.news.fed_reg import fetch_federal_register_articles
from sources.news.whitehouse import fetch_whitehouse_articles
from sources.news.omb import fetch_omb_articles

from sources.house.appropriations_maj import fetch_appr_maj_articles
from sources.house.appropriations_min import fetch_appr_min_articles
from sources.house.budget_maj import fetch_budg_maj_articles
from sources.house.budget_min import fetch_budg_min_articles
from sources.house.education_and_workforce_maj import fetch_eaw_maj_articles
from sources.house.education_and_workforce_min import fetch_eaw_min_articles
from sources.house.energy_and_commerce_maj import fetch_eac_maj_articles
from sources.house.energy_and_commerce_min import fetch_eac_min_articles
from sources.house.homeland_maj import fetch_home_maj_articles
from sources.house.homeland_min import fetch_home_min_articles
from sources.house.joint_economic_maj import fetch_jec_maj_articles
from sources.house.joint_economic_min import fetch_jec_min_articles
from sources.house.judiciary_maj import fetch_jud_maj_articles
from sources.house.judiciary_min import fetch_jud_min_articles
from sources.house.natural_resources_maj import fetch_natr_maj_articles
from sources.house.natural_resources_min import fetch_natr_min_articles
from sources.house.oversight_maj import fetch_ovs_maj_articles
from sources.house.oversight_min import fetch_ovs_min_articles
from sources.house.rules_maj import fetch_rul_maj_articles
from sources.house.rules_min import fetch_rul_min_articles
from sources.house.small_business_maj import fetch_smb_maj_articles
from sources.house.small_business_min import fetch_smb_min_articles
from sources.house.veterans_maj import fetch_vet_maj_articles
from sources.house.veterans_min import fetch_vet_min_articles
from sources.house.ways_and_means_maj import fetch_wam_maj_articles
from sources.house.ways_and_means_min import fetch_wam_min_articles

from sources.senate.aging import fetch_age_articles
from sources.senate.appropriations import fetch_appr_articles
from sources.senate.budget import fetch_budg_articles
from sources.senate.finance import fetch_fin_articles
from sources.senate.help import fetch_help_articles
from sources.senate.homeland import fetch_home_articles
from sources.senate.indian import fetch_ind_articles
from sources.senate.judiciary import fetch_jud_articles
from sources.senate.small_business import fetch_smb_articles
from sources.senate.veterans import fetch_vet_articles


NEWS_SOURCES = {
    "CMS": fetch_cms_articles,
    "CRS": fetch_crs_articles,
    "Congress": fetch_congress_articles,
    "FDA": fetch_fda_articles,
    "Federal Register Public Inspection Desk": fetch_federal_register_articles,
    "OMB First Glance Rulemaking": fetch_omb_articles,
    "White House": fetch_whitehouse_articles,
}


HOUSE_SOURCES = {
    "Appropriations": {
        "majority": fetch_appr_maj_articles,
        "minority": fetch_appr_min_articles,
    },
    "Budget": {
        "majority": fetch_budg_maj_articles,
        "minority": fetch_budg_min_articles,
    },
    "Education and Workforce": {
        "majority": fetch_eaw_maj_articles,
        "minority": fetch_eaw_min_articles,
    },
    "Energy and Commerce (E&C)": {
        "majority": fetch_eac_maj_articles,
        "minority": fetch_eac_min_articles,
    },
    "Homeland Security": {
        "majority": fetch_home_maj_articles,
        "minority": fetch_home_min_articles,
    },
    "Joint Economic": {
        "majority": fetch_jec_maj_articles,
        "minority": fetch_jec_min_articles,
    },
    "Judiciary": {
        "majority": fetch_jud_maj_articles,
        "minority": fetch_jud_min_articles,
    },
    "Natural Resources": {
        "majority": fetch_natr_maj_articles,
        "minority": fetch_natr_min_articles,
    },
    "Oversight": {
        "majority": fetch_ovs_maj_articles,
        "minority": fetch_ovs_min_articles,
    },
    "Rules": {
        "majority": fetch_rul_maj_articles,
        "minority": fetch_rul_min_articles,
    },
    "Small Business": {
        "majority": fetch_smb_maj_articles,
        "minority": fetch_smb_min_articles,
    },
    "Veterans Affairs": {
        "majority": fetch_vet_maj_articles,
        "minority": fetch_vet_min_articles,
    },
    "Ways and Means": {
        "majority": fetch_wam_maj_articles,
        "minority": fetch_wam_min_articles,
    },
}


SENATE_SOURCES = {
    "Aging": fetch_age_articles,
    "Appropriations": fetch_appr_articles,
    "Budget": fetch_budg_articles,
    "Finance": fetch_fin_articles,
    "Health, Education, Labor & Pensions (HELP)": fetch_help_articles,
    "Homeland Security and Governmental Affairs (Oversight)": fetch_home_articles,
    "Indian Affairs": fetch_ind_articles,
    "Judiciary": fetch_jud_articles,
    "Veterans Affairs": fetch_vet_articles,
    "Small Business": fetch_smb_articles,
}
