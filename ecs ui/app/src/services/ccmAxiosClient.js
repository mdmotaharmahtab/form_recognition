import axios from "axios";
import { CCM_API_BASE_URL, CCM_URL_TOKEN } from "../../constant";

const ccmAxiosClient = axios.create({
  baseURL: CCM_API_BASE_URL,
  headers: {
    Authorization: `Bearer ${CCM_URL_TOKEN}`,
  },
});

export default ccmAxiosClient;