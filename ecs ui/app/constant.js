export const Backend_LOCAL_PROXY = process.env.REACT_API_BASE_URL;
export const Frontend_LOCAL_PROXY = process.env.REACT_APP_BASE_URL
export const ecsUtilsURL = process.env.REACT_APP_ECS_UTILS_URL;
export const ecsPlatformAgentsURL = process.env.REACT_APP_ECS_PLATFORM_URL;
export const ecsUtilsURLToken = process.env.REACT_APP_ECS_UTILS_TOKEN;
export const ecsPlatformAgentsURLToken = process.env.REACT_APP_ECS_PLATFORM_TOKEN;
export const ASK_URL_TOKEN = process.env.REACT_ASK_URL_TOKEN;
export const ASK_URL = `${process.env.REACT_ASK_BASE_URL}${process.env.REACT_ASK_URL_PATH}`;
export const CCM_API_BASE_URL = process.env.REACT_APP_CCM_API_BASE_URL
export const CCM_URL_TOKEN = process.env.REACT_APP_CCM_URL_TOKEN
export const CCM_UTILS_TOKEN = process.env.REACT_APP_CCM_UTILS_TOKEN
export const CCM_UTILS_API_BASE_URL = "/ccm-utils/v1/ccm_utils";
export const MY_PROJECTS = ["ECS", "CCM"]
export const ROLE_MAP = {
  "1": "SYSTEM_SUPPORT_ADMIN",
  "2": "BUSINESS_ADMIN",
  "3": "WRITER",
  "4": "SUPER_ADMIN"
};

