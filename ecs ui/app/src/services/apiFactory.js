import axios from "axios";

export const createApi = ({ baseURL, utilsURL, utilsToken, platformAgentsToken, ASK_URL, ASK_URL_TOKEN }) => {
  const api = axios.create({
    baseURL,
    headers: {
      "Content-Type": "application/json",
    },
  });

  api.interceptors.request.use((config) => {
    if (utilsURL && config.url.includes(utilsURL)) {
      config.headers.Authorization = `Bearer ${utilsToken}`;
    } else if (config.url.includes(ASK_URL)) {
      config.headers.Authorization = `Bearer ${ASK_URL_TOKEN}`;
    } else {
      config.headers.Authorization = `Bearer ${platformAgentsToken}`;
    }
    return config;
  });

  return api;
};
