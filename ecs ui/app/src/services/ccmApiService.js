import ccmAxiosClient from "./ccmAxiosClient";
import ccmUtilsAxiosClient from "./ccmUtilsAxiosClient";

/**
 * Wraps an async API call, timing it and logging the latency to console.
 * Re-throws on failure after logging, so existing error handling is untouched.
 */
const withLatency = async (label, fn) => {
  const start = performance.now();
  try {
    const result = await fn();
    const duration = (performance.now() - start).toFixed(2);
    console.log(`[API Latency] ${label}: ${duration}ms`);
    return result;
  } catch (error) {
    const duration = (performance.now() - start).toFixed(2);
    console.log(`[API Latency] ${label} (failed): ${duration}ms`);
    throw error;
  }
};

/**
 * Submit all files at once for batch processing
 * Files are uploaded, OCR'd, and queued for classification + extraction
 * Returns immediately with job_id (processing happens in background)
 */
export const submitJob = async (payload) => {
  return withLatency("submitJob", async () => {
    try {
      const response = await ccmAxiosClient.post(`/api/v1/ccm_processing_dev/submit_job/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Job submission failed:", error);
      throw error;
    }
  });
};

/**
 * Poll job status (call every 30 seconds until job_status = COMPLETED/FAILED)
 * Returns job-level status + per-file classification and field extraction results
 */
export const getJobStatus = async (payload) => {
  return withLatency("getJobStatus", async () => {
    try {
      const response = await ccmAxiosClient.post(`/api/v1/ccm_processing_dev/job_status/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch job status:", error);
      throw error;
    }
  });
};

export const uploadDocument = async (payload) => {
  return withLatency("uploadDocument", async () => {
    try {
      const response = await ccmAxiosClient.post(`/upload_file/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Upload failed:", error);
      throw error;
    }
  });
};

export const getContractDigitizationStatus = async (payload) => {
  return withLatency("getContractDigitizationStatus", async () => {
    try {
      const response = await ccmAxiosClient.post(`/get-contract-digitization-status/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch digitization percent:", error);
      throw error;
    }
  });
};

// export const computeContractClassification = async (payload, signal) => {
//   try {
//     const response = await ccmAxiosClient.post(`/compute-contract-classification/run`, payload, { signal });
//     return response.data.response;
//   } catch (error) {

//     console.error("Upload failed:", error);
//     throw error;
//   }
// };

export const computeContractClassification = async (payload, signal) => {
  return withLatency("computeContractClassification (total)", async () => {
    try {
      // Call BOTH APIs in parallel, each individually timed
      const [classificationRes, metadataRes] = await Promise.all([
        withLatency("computeContractClassification -> compute-contract-classification", () =>
          ccmUtilsAxiosClient.post(`/compute-contract-classification/run`, payload, { signal })
        ),
        withLatency("computeContractClassification -> ccm-field-extraction", () =>
          ccmAxiosClient.post(`/ccm-field-extraction/run`, payload, { signal })
        ),
      ]);

      const classificationData = classificationRes?.data?.response || [];
      const metadataData = metadataRes?.data?.response || [];

      // Merge responses by file_id
      const metadataMap = new Map();
      metadataData.forEach((item) => {
        metadataMap.set(item.file_id, item.metadata || {});
      });

      const mergedResponse = classificationData.map((item) => ({
        ...item,
        metadata: metadataMap.get(item.file_id) || {}
      }));

      return mergedResponse;

    } catch (error) {
      console.error("Upload failed:", error);
      throw error;
    }
  });
};

// {
//    "file_id": "ca0b6ad3-41c0-407f-af82-f4d484b81248",
//    "metadata_key_name": "Organization",
//    "is_liked_flag": true,
//    "job_id": ""
// }

export const contractFeatureToggle = async (payload) => {
  return withLatency("contractFeatureToggle", async () => {
    try {
      const response = await ccmAxiosClient.post(`/api/v1/ccm_processing_dev/contract-feature-toggle/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch digitization percent:", error);
      throw error;
    }
  });
};

// {
//    "user_id": "Lokesh.Malviya",
//    "file_ids": [
//       "c680872c-11ac-40b8-babf-ccade1acc7e5",
//       "75722e2d-e6a4-4698-a0c9-ba9f238cf265"
//    ],
//    "job_id":""
// }

export const fetchContractDetails = async (payload) => {
  return withLatency("fetchContractDetails", async () => {
    try {
      const response = await ccmAxiosClient.post(`/fetch-contract-details/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch digitization percent:", error);
      throw error;
    }
  });
};

//read-contract-classification
// {
//    "file_ids": [
//       "ca0b6ad3-41c0-407f-af82-f4d484b81248"
//    ],
//    "job_id": ""
// }
export const readContractClassification = async (payload) => {
  return withLatency("readContractClassification", async () => {
    try {
      const response = await ccmAxiosClient.post(`/read-contract-classification/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch digitization percent:", error);
      throw error;
    }
  });
};


export const contractClassificationFeedback = async (payload) => {
  return withLatency("contractClassificationFeedback", async () => {
    try {
      const response = await ccmAxiosClient.post(`/api/v1/ccm_processing_dev/contract-classification-feedback/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to fetch digitization percent:", error);
      throw error;
    }
  });
};

export const exportDocument = async (payload) => {
  return withLatency("exportDocument", async () => {
    try {
      const response = await ccmAxiosClient.post(`/api/v1/ccm_processing_dev/export_document/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

// access managment APIs
export const getAccess = async (payload) => {
  return withLatency("getAccess", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/access/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const addProjectMember = async (payload) => {
  return withLatency("addProjectMember", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/add_project_member/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const getAllGlobalUsers = async (payload) => {
  return withLatency("getAllGlobalUsers", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_all_global_users/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const getAllProjectMemebers = async (payload) => {
  return withLatency("getAllProjectMemebers", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_all_project_memebers/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const getProjects = async (payload) => {
  return withLatency("getProjects", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_projects/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const removeProjectMember = async (payload) => {
  return withLatency("removeProjectMember", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/remove_project_member/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const updateProjectMemberRole = async (payload) => {
  return withLatency("updateProjectMemberRole", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/update_project_member_role/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

export const getData = async (payload) => {
  return withLatency("getData", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_data/run`, { payload: payload });
      return response.data.response;
    } catch (error) {
      console.error("Failed to export document:", error);
      throw error;
    }
  });
};

// ─── Monitoring / Admin Feedback ──────────────────────────────────────────────

export const getAllFeedback = async (payload) => {
  return withLatency("getAllFeedback", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_all_feedback/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to get all feedback:", error);
      throw error;
    }
  });
};

export const postAdminFeedback = async (payload) => {
  return withLatency("postAdminFeedback", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/post_admin_feedback/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to post admin feedback:", error);
      throw error;
    }
  });
};

export const getAllAdminFeedback = async (payload) => {
  return withLatency("getAllAdminFeedback", async () => {
    try {
      const response = await ccmUtilsAxiosClient.post(`/get_all_admin_feedback/run`, payload);
      return response.data.response;
    } catch (error) {
      console.error("Failed to get admin feedback history:", error);
      throw error;
    }
  });
};
