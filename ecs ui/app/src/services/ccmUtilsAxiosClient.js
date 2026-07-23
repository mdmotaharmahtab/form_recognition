import axios from "axios";
import { CCM_UTILS_API_BASE_URL, CCM_UTILS_TOKEN } from "../../constant";

const ccmUtilsAxiosClient = axios.create({
  baseURL: CCM_UTILS_API_BASE_URL,
  headers: {
    Authorization: `Bearer ${CCM_UTILS_TOKEN}`,
  },
});

export default ccmUtilsAxiosClient;