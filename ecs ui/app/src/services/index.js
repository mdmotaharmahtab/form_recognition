import { api } from "./api"; // path to your axios instance file
import { ASK_URL, ASK_URL_TOKEN, ecsUtilsURL, ecsPlatformAgentsURL } from "../../constant";
import { extractLastTwo } from "./functions";
import { encryptPayload } from "./encryptPayload";

const CREATE_NEW_CHAT_SESSION = `${ASK_URL}/create-new-chat-session/run`;
const GET_RESPONSE = `${ASK_URL}/generate_response/run`;
const RENAME_SESSION = `${ASK_URL}/rename-session/run`;

/**
 * Converts a File to a base64 string
 */
export const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      const result = reader.result;
      const base64 = result.split(",")[1];
      resolve(base64);
    };

    reader.onerror = (error) => reject(error);
    reader.readAsDataURL(file);
  });
};

/**
 * Uploads a protocol file as base64
 */
export const uploadProtocol = async (payload) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/file-upload/run`, payload);

    return response.data.response;
  } catch (error) {
    console.error("Upload failed:", error);
    throw error;
  }
};

/**
 * Digitizes a protocol
 */
export const digitizeProtocol = async (payload, signal) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/extract-crf/run`, payload, { signal });
    return response.data.response;
  } catch (error) {

    console.error("Upload failed:", error);
    throw error;
  }
};

/**
 * Generates Review table.
 *
 * @param {{ protocol_id: string }} payload - Payload object with a protocol ID.
 * @returns {Promise<any>} Response from the API.
 */

export const generateReviewTable = async (payload) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/generate-review-table/run`, payload);

    // Extract result array safely (support both structures)
    const resultArray = Array.isArray(response?.data?.response)
      ? response.data.response
      : response?.data?.response?.result;

    // Validate it’s an array
    if (!Array.isArray(resultArray)) {
      const errorMessage =
        typeof response?.data?.response === "string"
          ? response.data.response
          : JSON.stringify(response?.data?.response || "Error while generating review table");

      throw new Error(errorMessage);
    }

    console.log("generateReviewTable: ", resultArray);
    return resultArray;
  } catch (error) {
    console.error("Error while generating review table failed:", error);
    throw error;
  }
};



/**
 * LLM generate.
 *
 * @param {{
 *   form_name: string,
 *   field_name: string,
 * }} payload - LLM generate.
 * @returns {Promise<any>} Response from the API.
 */
export const generateLLMECS = async (payload) => {
  try {
    const response = await api.post(`${ecsPlatformAgentsURL}/ecs-generation/run`, payload);
    return response.data.response;
  } catch (error) {
    console.error("Add assessment failed:", error);
    throw error;
  }
};

/**
 * Adds a new assessment to the protocol.
 *
 * @param {{
 *   protocol_id: string,
 *   assessment_id: string,
 *   assessment_name: string,
 *   form_name: string,
 *   template_name: string,
 *   source: string
 * }} payload - Assessment details to add.
 * @returns {Promise<any>} Response from the API.
 */
export const addAssessment = async (payload) => {
  try {
    const response = await api.post(`${ecsPlatformAgentsURL}/ecs-generation/run`, payload);
    return response.data.response;
  } catch (error) {
    console.error("Add assessment failed:", error);
    throw error;
  }
};

/**
 * Fetches the current digitization progress for a given protocol.
 *
 * @param {{ file_id: string }} payload - Object containing the protocol ID.
 * @returns {Promise<{ digitization_percent: string }>} The digitization percentage as a string.
 */
export const getDigitizationPercent = async ({ file_id }) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/digitization-percent/run`, { file_id });
    return response.data.response;
  } catch (error) {
    console.error("Failed to fetch digitization percent:", error);
    throw error;
  }
};

export const getIndication = async () => {
  try {
    const response = await api.post(`${ecsUtilsURL}/get-indication/run`, {});
    return response.data.response;
  } catch (error) {
    console.error("Failed to fetch indication:", error);
    throw error;
  }
};

export const getAllEcs = async (payload) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/get-all-ecs/run`, payload);
    return response.data.response;
  } catch (error) {
    console.error("Failed to fetch indication:", error);
    throw error;
  }
};

export const getSpecificEcs = async (payload) => {
  try {
    const response = await api.post(`${ecsUtilsURL}/get-specific-ecs/run`, payload);
    return response.data.response;
  } catch (error) {
    console.error("Failed to fetch indication:", error);
    throw error;
  }
};

export const fetchPost = async (url, body, token = "") => {
  // const { user_id } = getUserDetails();
  const edgeCaseEndpoints = ["convert_to_pdf", "generate_response", "get_response", "digitize_files"];
  const urlEndPoint = extractLastTwo(url);
  const notToEncryptEndPoints = ["upload_doc"];

  if (!notToEncryptEndPoints.some((str) => urlEndPoint.includes(str))) {
    body = await encryptPayload(body);
  }

  const startTime = Date.now();
  try {
    const response = await api.post(url, body, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    const endTime = Date.now();
    const timeTaken = Math.floor((endTime - startTime) / 1000);

    if (response?.status === 200) {
      // const { isError, matched } = isErrorResponse(response?.data?.response);
      // let response_message = response?.data?.response?.message || response?.data?.response?.status || response?.data?.response?.Status || (isError ? matched : "API called successfully!")
      const statusCode = response?.data?.response?.status_code;
      const isSuccess = statusCode === 200 || statusCode === undefined;
      const response_message = isSuccess ? "API called successfully!" : response?.data?.response?.error;
      const logLevel = isSuccess ? "info" : "error";

      // if (!isError && edgeCaseEndpoints.some(str => urlEndPoint.includes(str))) response_message = "API called successfully!";

      const message = `${urlEndPoint}, ${response_message}`;
      // sendLogs(isError ? "error" : "info", "skai", user_id, message, timeTaken);
      console.log(logLevel, "skai", "user_id", message, timeTaken);
      return response.data;
    } else {
      // const response_message = response?.data?.response?.message || response?.data?.response?.status || response?.data?.response?.Status || "Error with API call!";
      const response_message = "Error with API call!";
      const message = `${extractLastTwo(url)}, ${response_message}`;
      console.error("error", "skai", "user_id", message, timeTaken);
    }
  } catch (error) {
    const endTime = Date.now();
    const timeTaken = Math.floor((endTime - startTime) / 1000);

    const isSuccess = error?.status === 504 && edgeCaseEndpoints.some((str) => urlEndPoint.includes(str));
    const logLevel = isSuccess ? "info" : "error";
    const response_message = isSuccess
      ? "Request failed due to Gateway Timeout with status code 504"
      : error?.response?.data?.message || error?.message || error;
    const message = `${urlEndPoint}, ${response_message}`;
    console.log(logLevel, "skai", message, timeTaken);
    console.error("Failed to fetch AI response:", error);
    // const response_message = error?.response?.data?.message || error?.message || error;
    // const message = `${extractLastTwo(url)}, ${response_message}`;
    // sendLogs("error", "skai", user_id, message, timeTaken);
  }
};

export const createNewChatSession = async (payload) => {
  return fetchPost(CREATE_NEW_CHAT_SESSION, payload, ASK_URL_TOKEN).then((res) => res.response);
};

export const getAskAIResponse = async (payload) => {
  return fetchPost(GET_RESPONSE, payload, ASK_URL_TOKEN).then((res) => res.response);
};

export const renameSession = async (session_id, session_name) => {
  return fetchPost(RENAME_SESSION, { session_id, session_name }, ASK_URL_TOKEN).then((res) => res);
};
