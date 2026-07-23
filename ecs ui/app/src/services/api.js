import { createApi } from "./apiFactory";
import { Backend_LOCAL_PROXY, ecsUtilsURLToken, ecsUtilsURL, ecsPlatformAgentsURLToken, ASK_URL, ASK_URL_TOKEN } from "../../constant";


export const api = createApi({
  baseURL: Backend_LOCAL_PROXY,  //process.env.NODE_ENV === "production" ? "https://api-aiwriter-services-poc.otsuka-us.com" : "",
  utilsURL: ecsUtilsURL,
  utilsToken: ecsUtilsURLToken,
  platformAgentsToken: ecsPlatformAgentsURLToken,
  ASK_URL,
  ASK_URL_TOKEN
});
