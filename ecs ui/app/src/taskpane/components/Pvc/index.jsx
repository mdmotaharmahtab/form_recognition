import React, { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Tooltip, Modal, message, Space } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import UploadSourceDocument from "./UploadSourceDocument";
import { PvcContext } from "../../contexts/PvcContext";
import { useAuth } from "../../contexts/AuthContext";
import customMessage from "../customMessage";
import { Frontend_LOCAL_PROXY } from "../../../../constant";
import { submitJob, getJobStatus } from "../../../services/ccmApiService";
import { writeCCMResponseToExcel } from "../../taskpane";
import { useRole } from "../../contexts/RoleContext";
import UserTable from "../User/UserTable";
import MonitoringTable from "../User/MonitoringTable";

const POLL_INTERVAL = 30000; // Poll every 30 seconds
const MAX_TRANSIENT = 3; // Tolerate this many consecutive NOT_FOUND / network blips before giving up

const Pvc = ({ onBack }) => {
  const [fileList, setFileList] = useState([]);
  const [protocolId, setProtocolId] = useState(null);
  const [dataSource, setDataSource] = useState([]);
  const [tip, setTip] = useState("Loading, please wait...");
  const [loading, setLoading] = useState(false);
  const [isFileDigitized, setIsFileDigitized] = useState(true);
  const [progress, setProgress] = useState(null);
  const [templateProgress, setTemplateProgress] = useState(null);
  const [templateProgressCompleted, setTemplateProgressCompleted] = useState(null);
  const [totalTemplate, setTotalTemplate] = useState(0);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [indication, setIndication] = useState({ indication: "", molecule: "", ta: "" });
  const [jobId, setJobId] = useState(null);
  const [digitizedResult, setDigitizeResult] = useState([]);
  const [fileIds, setFileIds] = useState([]);
  const [processingComplete, setProcessingComplete] = useState(false);

  const dialogRef = useRef(null);
  const pollIntervalRef = useRef(null);
  const uploadedFilesRef = useRef([]);

  const { user } = useAuth();
  const { userSelected, setSelectedProject, monitoringSelected } = useRole();


  const clearPolling = () => {
    if (pollIntervalRef.current) {
      clearTimeout(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  // Safe wrapper to send a message to dialog
  const sendToDialog = (dialogInstance, payload) => {
    try {
      dialogInstance?.messageChild(JSON.stringify(payload));
    } catch (e) {
      console.warn("sendToDialog failed:", e);
    }
  };

  // Open dialog and wait for "ready" signal
  const openDialog = (jobId, totalFiles) => {
    return new Promise((resolve) => {
      Office.context.ui.displayDialogAsync(
        `${Frontend_LOCAL_PROXY}/PvcReviewDialog.html`,
        { height: 100, width: 100 },
        (result) => {
          const dialog = result.value;
          dialogRef.current = dialog;

          dialog.addEventHandler(
            Office.EventType.DialogMessageReceived,
            (args) => {
              const data = JSON.parse(args.message);

              if (data.action === "ready") {
                sendToDialog(dialog, {
                  action: "init",
                  payload: {
                    jobId,
                    userId: user.username,
                    totalFiles,
                    result_json: [] // Will be populated by polling
                  }
                });
                resolve(dialog);
              }

              // User clicked Submit
              if (data.action === "close") {
                clearPolling();
                dialog.close();
                dialogRef.current = null;
                writeCCMResponseToExcel(data.payload);
              }

              // User closed via X
              if (data.action === "dismissed") {
                clearPolling();
                dialog.close();
                dialogRef.current = null;
              }

              // All files completed
              if (data.action === "allCompleted") {
                clearPolling();
                setProcessingComplete(true);
                if (data.payload?.jobId) setJobId(data.payload.jobId);
              }
            }
          );
        }
      );
    });
  };

  // Poll job status and update dialog.
  // Uses a self-scheduling setTimeout loop (not setInterval) so polls can never
  // overlap, plus a transient-error counter so a single NOT_FOUND / network blip
  // does NOT permanently kill polling while the job is still PROCESSING.
  const startPolling = (job_id, dialog) => {
    let stopped = false;
    let inFlight = false;
    let transient = 0;

    const sendMsg = (msg) => {
      try {
        (dialogRef.current || dialog)?.messageChild(msg);
      } catch (e) {
        console.warn("sendMsg failed:", e);
      }
    };

    const stop = () => {
      stopped = true;
      clearPolling();
    };

    const scheduleNext = () => {
      if (!stopped) {
        pollIntervalRef.current = setTimeout(poll, POLL_INTERVAL);
      }
    };

    const poll = async () => {
      if (stopped || inFlight) return; // never overlap
      inFlight = true;

      try {
        const response = await getJobStatus({
          job_id,
          user_id: user.username
        });

        console.log("[POLL] Job status:", response);

        const {
          status,
          results,
          total_files,
          processed_files,
          message: statusMsg
        } = response || {};

        // Update dialog with results FIRST, so the table has merged the latest
        // rows before any terminal status (COMPLETED/FAILED) is processed.
        if (results && results.length > 0) {
          const formattedResults = results.map((r, idx) => ({
            temp_id: `result-${idx}`,
            file_id: r.file_id,
            file_name: r.file_name,
            is_pv: r.is_pv,
            pv_confidence: r.pv_confidence,
            reason: r.reason,
            metadata: r.metadata,
            orig_language: r.orig_language,
            feedback: r.feedback ?? null,
            classification_comment: r.classification_comment || "",
            extraction_comment: r.extraction_comment || "",
            created_at: r.created_at,
            status: "done"
          }));

          sendMsg(JSON.stringify({
            action: "updateResults",
            payload: formattedResults
          }));
        }

        // THEN update status. The dialog uses this (not result counts) as the
        // single source of truth for completion.
        sendMsg(JSON.stringify({
          action: "updateStatus",
          payload: {
            status,
            totalFiles: total_files,
            processedFiles: processed_files,
            message: statusMsg
          }
        }));

        // ----- Terminal / continue decisions -----
        if (status === "COMPLETED") {
          stop();
          setProcessingComplete(true);
          setJobId(job_id);
          message.success({
            content: `All ${total_files} file(s) processed successfully!`,
            duration: 6,
            key: "processing-complete"
          });

          // Store uploaded files for "Reopen Results"
          uploadedFilesRef.current = (results || []).map((r) => ({
            file_id: r.file_id,
            file_name: r.file_name
          }));
          return;
        }

        if (status === "FAILED") {
          stop();
          message.error({
            content: "Job processing failed. Please retry.",
            duration: 6,
            key: "processing-failed"
          });
          return;
        }

        if (status === "PROCESSING" || status === "PENDING") {
          transient = 0; // healthy response, reset tolerance
          return; // finally -> scheduleNext
        }

        // NOT_FOUND / undefined / unexpected status: treat as transient.
        // Don't kill polling on the first blip — the job may still be processing
        // and the backend is just momentarily inconsistent.
        transient += 1;
        console.warn(`[POLL] Anomalous status "${status}" (${transient}/${MAX_TRANSIENT})`);
        if (transient >= MAX_TRANSIENT) {
          stop();
          message.error({
            content: "Lost contact with the job. Please resubmit.",
            duration: 6,
            key: "job-not-found"
          });
        }
      } catch (error) {
        console.error("[POLL] Error:", error);
        // Network blip counts as transient too
        transient += 1;
        if (transient >= MAX_TRANSIENT) {
          stop();
          message.error({
            content: "Network issue while checking job status. Please retry.",
            duration: 6,
            key: "poll-network-error"
          });
        }
      } finally {
        inFlight = false;
        scheduleNext();
      }
    };

    // Kick off immediately; the loop self-schedules from here on.
    poll();
  };

  // Main upload handler using new async API
  const handleBase64Upload = async (base64Files) => {
    setLoading(true);
    setTip("Submitting files...");

    try {
      // Submit job (returns immediately)
      const response = await submitJob({
        user_id: user.username,
        files: base64Files
      });

      console.log("[SUBMIT] Response:", response);

      const { status, status_code, data: responseData } = response;

      if (status_code !== 200 && status_code !== 207) {
        const errMsg = status_code === 502
          ? "Server unavailable (502) — please retry"
          : status_code === 503
            ? "Service unavailable (503) — please retry"
            : status_code === 504
              ? "Request timeout (504) — please retry"
              : "Upload failed — please retry";

        message.error(errMsg);
        setLoading(false);
        return;
      }

      const job_id = responseData.job_id;
      const uploadedFiles = responseData.files || [];
      const failedFiles = responseData.failed || [];

      if (failedFiles.length > 0) {
        message.warning({
          content: `${failedFiles.length} file(s) failed to upload. Processing ${uploadedFiles.length} successful files.`,
          duration: 6
        });
      }

      if (uploadedFiles.length === 0) {
        message.error("All files failed to upload. Please retry.");
        setLoading(false);
        return;
      }

      // Open dialog and start polling
      const dialog = await openDialog(job_id, uploadedFiles.length);

      // Initialize dialog with file list
      const initialFileList = uploadedFiles.map((f, idx) => ({
        temp_id: `file-${idx}`,
        file_id: f.file_id,
        file_name: f.file_name,
        status: "processing"
      }));

      sendToDialog(dialog, {
        action: "updateResults",
        payload: initialFileList
      });

      // Start polling for results (self-scheduling loop, do not await)
      startPolling(job_id, dialog);

      message.success({
        content: `Processing ${uploadedFiles.length} file(s)...`,
        duration: 4
      });

    } catch (error) {
      console.error("[SUBMIT] Error:", error);
      const errMsg = !navigator.onLine
        ? "No internet connection"
        : error?.message || "Unexpected error during upload";
      message.error(errMsg);
    } finally {
      setLoading(false);
    }
  };

  // Reopen results dialog for completed job
  const onClickGenerate = async (jobId) => {
    setLoading(true);

    try {
      const response = await getJobStatus({
        job_id: jobId,
        user_id: user.username
      });

      console.log("[GENERATE] Job status:", response);

      const { status, results } = response;

      if (status === "NOT_FOUND") {
        customMessage.error("Job not found. Please re-upload your files.");
        setLoading(false);
        return;
      }

      if (status === "PROCESSING" || status === "PENDING") {
        customMessage.info("Job is still processing. Please wait...");
        setLoading(false);
        return;
      }

      if (status === "FAILED") {
        customMessage.error("Job processing failed. Please retry.");
        setLoading(false);
        return;
      }

      if (!results || results.length === 0) {
        customMessage.error("No results found for this job.");
        setLoading(false);
        return;
      }

      // Format results for dialog
      const formattedResults = results.map((r) => ({
        file_id: r.file_id,
        file_name: r.file_name,
        is_pv: r.is_pv,
        pv_confidence: r.pv_confidence,
        reason: r.reason,
        metadata: r.metadata,
        orig_language: r.orig_language,
        feedback: r.feedback ?? null,
        classification_comment: r.classification_comment || "",
        extraction_comment: r.extraction_comment || "",
        created_at: r.created_at,
        status: "done"
      }));

      // Open dialog with results
      if (Office.context.ui) {
        Office.context.ui.displayDialogAsync(
          `${Frontend_LOCAL_PROXY}/PvcReviewDialog.html`,
          { height: 100, width: 100 },
          (result) => {
            const dialog = result.value;
            dialogRef.current = dialog;

            dialog.addEventHandler(Office.EventType.DialogMessageReceived, async (args) => {
              const data = JSON.parse(args.message);

              if (data.action === "ready") {
                setTimeout(() => {
                  sendToDialog(dialog, {
                    action: "init",
                    payload: {
                      result_json: formattedResults,
                      jobId,
                      userId: user.username,
                      totalFiles: formattedResults.length,
                      notShowProgress: true
                    }
                  });

                  // Add this: tell the dialog the job is already complete
                  sendToDialog(dialog, {
                    action: "updateStatus",
                    payload: {
                      status: "COMPLETED",
                      totalFiles: formattedResults.length,
                      processedFiles: formattedResults.length,
                    }
                  });
                }, 100);
}

              if (data.action === "close") {
                const processed = data.payload || [];
                dialog.close();
                dialogRef.current = null;
                console.log("Data from Popup", processed);
                await writeCCMResponseToExcel(processed);
              }

              if (data.action === "dismissed") {
                dialog.close();
                dialogRef.current = null;
              }
            });
          }
        );
      }
    } catch (error) {
      console.error("[GENERATE] Error:", error);
      customMessage.error("Failed to fetch job results.");
    } finally {
      setLoading(false);
    }
  };

  const highlightExcelRow = async (record) => {
    await Excel.run(async (context) => {
      const sheet = context.workbook.worksheets.getActiveWorksheet();
      const table = sheet.tables.getItemOrNullObject("FormData");
      await context.sync();

      if (table.isNullObject) {
        console.warn("FormData table not found.");
        return;
      }

      const dataRange = table.getDataBodyRange();
      dataRange.load("values");
      await context.sync();

      const values = dataRange.values;
      const matchIndex = values.findIndex((r) => r[12] === record.ecs_id);

      if (matchIndex === -1) {
        console.warn("Row not found in Excel table.");
        return;
      }

      const targetRow = dataRange.getRow(matchIndex);
      dataRange.format.fill.clear();
      targetRow.format.fill.color = "#FFE58F";
      targetRow.select();
      await context.sync();

      setTimeout(async () => {
        await Excel.run(async (ctx) => {
          const sheet = ctx.workbook.worksheets.getActiveWorksheet();
          const table = sheet.tables.getItemOrNullObject("FormData");
          const range = table.getDataBodyRange();
          range.load("values");
          await ctx.sync();
          if (matchIndex >= 0 && matchIndex < range.getRowCount()) {
            const targetRow = range.getRow(matchIndex);
            targetRow.format.fill.clear();
            await ctx.sync();
          }
        });
      }, 3000);
    });
  };

  const columns = [
    { title: "Form", dataIndex: "form_name", key: "form_name", width: 150, ellipsis: true },
    { title: "Field", dataIndex: "field_oids", key: "field_oids", width: 100, ellipsis: true },
    {
      title: "Action", key: "action", width: 50,
      render: (_, record) => (
        <div>
          <Space size="small">
            <Tooltip title="highlight Excel Row">
              <EyeOutlined
                style={{ color: "#426bba !important", cursor: "pointer" }}
                onClick={() => highlightExcelRow(record)}
              />
            </Tooltip>
          </Space>
        </div>
      ),
    },
  ];

  const handleBack = () => {
    const isFileListEmpty = fileList.length === 0;
    Modal.confirm({
      title: isFileListEmpty ? "Are you sure?" : "Discard Changes?",
      content: isFileListEmpty
        ? "Do you want to go back?"
        : "Your file will be discarded if you go back. Are you sure?",
      okText: "Yes, Go Back",
      cancelText: "Stay",
      okType: "danger",
      onOk() {
        clearPolling();
        setProtocolId(null);
        setIsFileDigitized(false);
        setFileList([]);
        setDataSource([]);
        setProcessingComplete(false);
        setJobId(null);
        uploadedFilesRef.current = [];
        setSelectedProject(null)
        if (onBack) onBack();
      },
      onCancel() {
        console.log("Stay on page");
      },
    });
  };

  const pvcContextValue = {
    loading,
    setLoading,
    setFileList,
    fileList,
    handleBase64Upload,
    dataSource,
    columns,
    onClickGenerate,
    handleBack,
    onBack,
    tip,
    setTip,
    isFileDigitized,
    setIsFileDigitized,
    progress,
    protocolId,
    setProtocolId,
    templateProgress,
    templateProgressCompleted,
    totalTemplate,
    templateLoading,
    indication,
    setIndication,
    jobId,
    setJobId,
    digitizedResult,
    fileIds,
    processingComplete,
  };


  return (
    <PvcContext.Provider value={pvcContextValue}>
      {userSelected ? (
        <UserTable />
      ) : monitoringSelected ? (
        <MonitoringTable />
      ) : (
        <UploadSourceDocument />
      )}
    </PvcContext.Provider>
  );
};

export default Pvc;

Office.onReady().then(() => {
  const root = document.getElementById("pvc_container");
  if (root) {
    console.log("Inside if");
    createRoot(root).render(<Pvc />);
  } else {
    console.log("Root element not found");
  }
});
