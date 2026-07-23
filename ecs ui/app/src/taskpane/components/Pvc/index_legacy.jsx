import React, { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Tooltip, Modal, message, Space } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import UploadSourceDocument from "./UploadSourceDocument";
import { PvcContext } from "../../contexts/PvcContext";
import { useAuth } from "../../contexts/AuthContext";
import customMessage from "../customMessage";
import { Frontend_LOCAL_PROXY } from "../../../../constant";
import { computeContractClassification, readContractClassification, uploadDocument } from "../../../services/ccmApiService";
import { writeCCMResponseToExcel } from "../../taskpane";

const MAX_RETRY_ATTEMPTS = 1; // Number of times to retry all failed files after the initial run
const BATCH_SIZE = 1;         // Number of files to upload/process per batch

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

  // true once ALL files have reached "done" or "error"
  // Used to show "Reopen Results" button if dialog was accidentally closed
  const [processingComplete, setProcessingComplete] = useState(false);

  const dialogRef = useRef(null);

  // Stores { file_name, document_id } for every successfully uploaded file
  // Persisted here because fileList only has raw browser File objects (no document_id)
  // Used by onClickGenerate to call readContractClassification with real IDs
  const uploadedFilesRef = useRef([]);

  // Tracks total vs finished files across all batches
  // Allows detecting completion without relying on the dialog
  const processingTrackerRef = useRef({ total: 0, finished: 0, jobId: null });

  // Collects failed files during a run so they can be retried after all batches finish.
  // Each entry: { temp_id, file_name, base64Data, error_stage: "upload"|"compute"|"read" }
  const failedFilesRef = useRef([]);

  // Map of temp_id → original base64 file object, needed to re-upload failed files
  const base64FileMapRef = useRef({});

  const { user } = useAuth();

  const pollIntervalRef = useRef(null);
  const abortControllerRef = useRef(null);

  const abortControllerHandle = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const clearIntervalHandle = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
  };

  const chunkArray = (arr, size = BATCH_SIZE) => {
    const res = [];
    for (let i = 0; i < arr.length; i += size) {
      res.push(arr.slice(i, i + size));
    }
    return res;
  };

  // Safe wrapper to send a message to any dialog instance
  const sendToDialog = (dialogInstance, payload) => {
    try {
      dialogInstance?.messageChild(JSON.stringify(payload));
    } catch (e) {
      console.warn("sendToDialog failed:", e);
    }
  };

  // Called every time any file finishes (done or error)
  // When all files are accounted for → marks processingComplete = true
  // and shows a toast so user knows they can reopen results
  const onFileFinished = (job_id) => {
    const tracker = processingTrackerRef.current;
    tracker.finished += 1;
    if (job_id) tracker.jobId = job_id;

    if (tracker.finished >= tracker.total && tracker.total > 0) {
      setProcessingComplete(true);
      if (tracker.jobId) setJobId(tracker.jobId);
      message.success({
        content: "All contracts processed — results are ready.",
        duration: 6,
        key: "processing-complete"
      });
    }
  };

  // openDialog returns a Promise that resolves only when dialog
  // sends back "ready" — guarantees dialogRef is set and dialog is
  // initialised before any batch error/success sends a message to it.
  // This fixes the 502/503 race condition (upload fails after 34s,
  // by which time dialogRef was still null → messages silently dropped)
  const openDialog = (jobId, file_ids) => {
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
                    // First batch pre-set to "processing", rest "pending"
                    result_json: file_ids,
                    jobId,
                    userId: user.username,
                    totalFiles: file_ids.length
                  }
                });
                // Resolve — callers can now safely send messages
                resolve(dialog);
              }

              // User clicked Submit — write results to Excel
              if (data.action === "close") {
                dialog.close();
                dialogRef.current = null;
                writeCCMResponseToExcel(data.payload);
              }

              // Dialog signals all files finished (done/error)
              // Set processingComplete even while dialog is still open
              // so "Reopen Results" is ready if user closes via X after this
              if (data.action === "allCompleted") {
                const completedJobId = data.payload?.jobId || processingTrackerRef.current.jobId;
                setProcessingComplete(true);
                if (completedJobId) setJobId(completedJobId);
              }

              // User closed dialog via X (not Submit)
              // Don't write to Excel, keep jobId so they can reopen
              if (data.action === "dismissed") {
                dialog.close();
                dialogRef.current = null;
                // processingComplete + jobId stay set →
                // UploadSourceDocument shows "Reopen Results" button
              }
            }
          );
        }
      );
    });
  };

  // processBatch receives a stable sendMsg closure captured
  // at call-time. Previously it read dialogRef.current directly,
  // which could be null/stale after a 40+ second async gap —
  // causing all error messages to be silently dropped and files
  // to stay stuck on "Analyzing..." forever.
  const processBatch = async (fileIds, job_id, mappedBatch, sendMsg) => {
    const send = (payload) => {
      try {
        sendMsg(JSON.stringify({ action: "append", payload }));
      } catch (e) {
        console.warn("processBatch send failed:", e);
      }
    };

    // Count files in this batch as finished in the tracker
    const markFinished = (count = mappedBatch.length) => {
      for (let i = 0; i < count; i++) {
        onFileFinished(job_id);
      }
    };

    try {
      // ================= COMPUTE =================
      let computeFailed = false;
      let computeErrorMsg = "Compute API failed — please retry";

      try {
        await computeContractClassification({
          user_id: user.username,
          job_id,
          file_ids: fileIds
        });
      } catch (e) {
        console.error("Compute failed:", e);
        computeFailed = true;
        const status = e?.response?.status || e?.status;
        if (status === 500) computeErrorMsg = "Compute API error (500) — server error";
        else if (status === 503) computeErrorMsg = "Compute API unavailable (503) — please retry";
        else if (status === 504) computeErrorMsg = "Compute API timed out (504) — please retry";
        else if (e?.name === "AbortError") computeErrorMsg = "Compute request was cancelled";
        else if (!navigator.onLine) computeErrorMsg = "No internet connection";
      }

      if (computeFailed) {
        // Record these files as failed at compute stage for potential retry
        mappedBatch.forEach((m) => {
          failedFilesRef.current.push({
            temp_id: m.temp_id,
            file_name: m.file_name,
            error_stage: "compute",
            // file_id is known (upload succeeded), so we can skip re-upload on retry
            file_id: m.file_id
          });
        });

        send(mappedBatch.map((m) => ({
          temp_id: m.temp_id,
          file_id: m.file_id || m.temp_id,   // include file_id so dialog can match by either key
          status: "error",
          error_message: computeErrorMsg
        })));
        markFinished();
        return;
      }

      // ================= READ =================
      let response = [];
      let readErrorMsg = "Read classification API failed — please retry";

      try {
        response = await readContractClassification({
          file_ids: fileIds,
          job_id,
          user_id: user.username
        });
      } catch (err) {
        console.error("Read API failed:", err);
        const status = err?.response?.status || err?.status;
        if (status === 500) readErrorMsg = "Read API error (500) — server error";
        else if (status === 503) readErrorMsg = "Read API unavailable (503) — please retry";
        else if (status === 504) readErrorMsg = "Read API timed out (504) — please retry";
        else if (err?.name === "AbortError") readErrorMsg = "Read request was cancelled";
        else if (!navigator.onLine) readErrorMsg = "No internet connection";

        // Record as failed at read stage
        mappedBatch.forEach((m) => {
          failedFilesRef.current.push({
            temp_id: m.temp_id,
            file_name: m.file_name,
            error_stage: "read",
            file_id: m.file_id
          });
        });

        send(mappedBatch.map((m) => ({
          temp_id: m.temp_id,
          file_id: m.file_id || m.temp_id,   // include file_id so dialog can match by either key
          status: "error",
          error_message: readErrorMsg
        })));
        markFinished();
        return;
      }

      // Empty / invalid response
      if (!Array.isArray(response) || response.length === 0) {
        mappedBatch.forEach((m) => {
          failedFilesRef.current.push({
            temp_id: m.temp_id,
            file_name: m.file_name,
            error_stage: "read",
            file_id: m.file_id
          });
        });

        send(mappedBatch.map((m) => ({
          temp_id: m.temp_id,
          file_id: m.file_id,   // include file_id so dialog can match by either key
          status: "error",
          error_message: "No classification results returned — please retry"
        })));
        markFinished();
        return;
      }

      // ================= SUCCESS =================
      const finalPayload = response.map((resItem, idx) => {
        const matched =
          mappedBatch.find(m => m.file_id === resItem.file_id) ||
          mappedBatch[idx];
        return {
          ...resItem,
          temp_id: matched?.temp_id,
          status: "done"
        };
      });

      const returnedIds = new Set(response.map(r => r.file_id));
      // find missing files
      const missing = mappedBatch
        .filter(m => !returnedIds.has(m.file_id))
        .map(m => {
          // Record missing files as failed for retry
          failedFilesRef.current.push({
            temp_id: m.temp_id,
            file_name: m.file_name,
            error_stage: "read",
            file_id: m.file_id
          });
          return {
            temp_id: m.temp_id,
            file_id: m.file_id,
            status: "error",
            error_message: "Processing failed"
          };
        });

      const result = [...finalPayload, ...missing];
      send(result);
      markFinished(result.length);

    } catch (err) {
      console.error("Unexpected error in processBatch:", err);

      mappedBatch.forEach((m) => {
        failedFilesRef.current.push({
          temp_id: m.temp_id,
          file_name: m.file_name,
          error_stage: "compute",
          file_id: m.file_id
        });
      });

      send(mappedBatch.map((m) => ({
        temp_id: m.temp_id,
        file_id: m.file_id,
        status: "error",
        error_message: "Unexpected error during processing"
      })));
      markFinished();
    }
  };

  // Retries all files that failed during a run.
  // Files that failed at "upload" stage are re-uploaded from scratch.
  // Files that failed at "compute" or "read" stages skip re-upload (file_id is known).
  // sendMsg is the captured dialog send closure from the original run.
  const retryFailedFiles = async (failedFiles, job_id, sendMsg) => {
    if (!failedFiles || failedFiles.length === 0) return;

    console.log(`[Retry] Retrying ${failedFiles.length} failed file(s)…`, failedFiles);

    message.info({
      content: `Retrying ${failedFiles.length} failed file(s)…`,
      duration: 4,
      key: "retry-start"
    });

    // Notify dialog so rows switch back to "processing" visually
    sendMsg(JSON.stringify({
      action: "append",
      payload: failedFiles.map((f) => ({
        temp_id: f.temp_id,
        status: "processing"
      }))
    }));

    // --- Split by what needs to happen ---
    const needUpload = failedFiles.filter((f) => f.error_stage === "upload");
    const skipUpload = failedFiles.filter((f) => f.error_stage !== "upload" && f.file_id);

    // --- Re-upload stage ---
    if (needUpload.length > 0) {
      const uploadBatches = chunkArray(needUpload, BATCH_SIZE);

      for (const batch of uploadBatches) {
        const base64Batch = batch
          .map((f) => base64FileMapRef.current[f.temp_id])
          .filter(Boolean);

        if (base64Batch.length === 0) {
          // Original file data not available — mark error
          sendMsg(JSON.stringify({
            action: "append",
            payload: batch.map((f) => ({
              temp_id: f.temp_id,
              status: "error",
              error_message: "Original file data unavailable — please re-upload"
            }))
          }));
          batch.forEach(() => onFileFinished(job_id));
          continue;
        }

        try {
          const res = await uploadDocument({
            user_id: user?.username,
            files: base64Batch
          });

          const responseData = res?.data || res?.response?.data || {};
          const statusCode = res?.status_code || res?.response?.status_code;
          const isSuccess = statusCode === 200;
          const isPartial = statusCode === 207;

          if (!isSuccess && !isPartial) {
            const errMsg =
              statusCode === 502 ? "Retry upload failed (502) — server unavailable"
                : statusCode === 503 ? "Retry upload failed (503) — service unavailable"
                  : statusCode === 504 ? "Retry upload failed (504) — gateway timeout"
                    : `Retry upload failed (${statusCode || "unknown error"})`;

            sendMsg(JSON.stringify({
              action: "append",
              payload: batch.map((f) => ({
                temp_id: f.temp_id,
                status: "error",
                error_message: errMsg
              }))
            }));
            batch.forEach(() => onFileFinished(job_id));
            continue;
          }

          const uploaded = responseData.uploaded || [];
          const failed = responseData.failed || [];
          const accountedTempIds = new Set();
          const mapped = [];

          for (const uploadedFile of uploaded) {
            const matched =
              batch.find((b) => b.file_name === uploadedFile.file_name) ||
              batch.find(
                (b) =>
                  uploadedFile.file_name?.includes(b.file_name) ||
                  b.file_name?.includes(uploadedFile.file_name)
              );
            if (!matched) continue;
            accountedTempIds.add(matched.temp_id);
            mapped.push({
              temp_id: matched.temp_id,
              file_id: uploadedFile.document_id,
              file_name: uploadedFile.file_name,
              status: "processing"
            });
          }

          for (const failedFile of failed) {
            const matched =
              batch.find((b) => b.file_name === failedFile.file_name) ||
              batch.find(
                (b) =>
                  failedFile.file_name?.includes(b.file_name) ||
                  b.file_name?.includes(failedFile.file_name)
              ) ||
              batch.find((b) => !accountedTempIds.has(b.temp_id));

            if (matched) {
              accountedTempIds.add(matched.temp_id);
              sendMsg(JSON.stringify({
                action: "append",
                payload: [{
                  temp_id: matched.temp_id,
                  status: "error",
                  error_message: failedFile.error || "Retry upload failed for this file"
                }]
              }));
              onFileFinished(job_id);
            }
          }

          for (const batchFile of batch) {
            if (!accountedTempIds.has(batchFile.temp_id)) {
              sendMsg(JSON.stringify({
                action: "append",
                payload: [{
                  temp_id: batchFile.temp_id,
                  status: "error",
                  error_message: "File was not processed by server on retry — please re-upload"
                }]
              }));
              onFileFinished(job_id);
            }
          }

          if (mapped.length > 0) {
            sendMsg(JSON.stringify({ action: "append", payload: mapped }));
            uploadedFilesRef.current = [
              ...uploadedFilesRef.current,
              ...mapped.map((m) => ({ file_name: m.file_name, document_id: m.file_id }))
            ];
            const ids = mapped.map((m) => m.file_id);
            await processBatch(ids, job_id, mapped, sendMsg);
          }

        } catch (e) {
          console.error("Retry upload batch exception:", e);
          const errMsg = !navigator.onLine ? "No internet connection"
            : e?.name === "AbortError" ? "Retry upload was cancelled"
              : e?.message || "Unexpected retry upload error";

          sendMsg(JSON.stringify({
            action: "append",
            payload: batch.map((f) => ({
              temp_id: f.temp_id,
              status: "error",
              error_message: errMsg
            }))
          }));
          batch.forEach(() => onFileFinished(job_id));
        }
      }
    }

    // --- Files that only need compute + read retried (upload already succeeded) ---
    if (skipUpload.length > 0) {
      const computeReadBatches = chunkArray(skipUpload, BATCH_SIZE);

      for (const batch of computeReadBatches) {
        const mapped = batch.map((f) => ({
          temp_id: f.temp_id,
          file_id: f.file_id,
          file_name: f.file_name,
          status: "processing"
        }));

        sendMsg(JSON.stringify({ action: "append", payload: mapped }));
        const ids = mapped.map((m) => m.file_id);
        await processBatch(ids, job_id, mapped, sendMsg);
      }
    }
  };

  const uploadAndDigitize = async (base64Files) => {
    let job_id = null;

    const filesWithTemp = base64Files.map((file, index) => ({
      ...file,
      temp_id: `temp-${index}`,
      file_name: file.file_name || file.name
    }));

    // Store base64 file data keyed by temp_id so retries can re-upload if needed
    base64FileMapRef.current = {};
    filesWithTemp.forEach((f) => {
      base64FileMapRef.current[f.temp_id] = f;
    });

    const batches = chunkArray(filesWithTemp, BATCH_SIZE);

    // Reset tracker, uploaded files list, and failed files list for this session
    processingTrackerRef.current = { total: filesWithTemp.length, finished: 0, jobId: null };
    uploadedFilesRef.current = [];
    failedFilesRef.current = [];
    setProcessingComplete(false);

    const initialFileList = filesWithTemp.map((f, i) => ({
      temp_id: f.temp_id,
      file_name: f.file_name,
      status: i < BATCH_SIZE ? "processing" : "pending"
    }));

    // Await dialog ready before starting loop
    const dialog = await openDialog(null, initialFileList);

    // Capture a stable sendMsg that always uses the latest dialogRef
    // (falls back to the resolved dialog from openDialog)
    const makeSendMsg = () => (msg) => {
      try { (dialogRef.current || dialog)?.messageChild(msg); }
      catch (e) { console.warn("sendMsg failed:", e); }
    };

    for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
      const batch = batches[batchIndex];
      const nextBatch = batches[batchIndex + 1];

      const sendMsg = makeSendMsg();

      try {
        if (batchIndex > 0) {
          sendMsg(JSON.stringify({
            action: "append",
            payload: batch.map((file) => ({
              temp_id: file.temp_id,
              status: "processing"
            }))
          }));
        }

        // Upload
        const res = await uploadDocument({
          user_id: user?.username,
          files: batch
        });

        const responseData = res?.data || res?.response?.data || {};
        const statusCode = res?.status_code || res?.response?.status_code;
        const isSuccess = statusCode === 200;
        const isPartial = statusCode === 207;

        if (!isSuccess && !isPartial) {
          // Total upload failure
          const errMsg =
            statusCode === 502 ? "Upload failed (502) — server unavailable"
              : statusCode === 503 ? "Upload failed (503) — service unavailable"
                : statusCode === 504 ? "Upload failed (504) — gateway timeout"
                  : `Upload failed (${statusCode || "unknown error"})`;

          // Record all batch files as failed at upload stage for retry
          batch.forEach((file) => {
            failedFilesRef.current.push({
              temp_id: file.temp_id,
              file_name: file.file_name,
              error_stage: "upload"
            });
          });

          sendMsg(JSON.stringify({
            action: "append",
            payload: batch.map((file) => ({
              temp_id: file.temp_id,
              file_id: file.temp_id,
              status: "error",
              error_message: errMsg
            }))
          }));

          batch.forEach(() => onFileFinished(job_id));

          if (nextBatch) {
            sendMsg(JSON.stringify({
              action: "append",
              payload: nextBatch.map((file) => ({
                temp_id: file.temp_id,
                status: "processing"
              }))
            }));
          }
          continue;
        }

        const uploaded = responseData.uploaded || [];
        const failed = responseData.failed || [];
        job_id = responseData.job_id || job_id;

        // Match by file_name — fixes missing file bug on partial response
        const mapped = [];

        // Track which batch files were accounted for
        // so we can catch any that fell through both uploaded + failed arrays
        const accountedTempIds = new Set();

        for (const uploadedFile of uploaded) {
          const matched =
            batch.find((b) => b.file_name === uploadedFile.file_name) ||
            // Fallback: partial name match (handles encoding/trim differences)
            batch.find(
              (b) =>
                uploadedFile.file_name?.includes(b.file_name) ||
                b.file_name?.includes(uploadedFile.file_name)
            );
          if (!matched) {
            console.warn("Could not match uploaded file:", uploadedFile.file_name);
            continue;
          }
          accountedTempIds.add(matched.temp_id);
          mapped.push({
            temp_id: matched.temp_id,
            file_id: uploadedFile.document_id,
            file_name: uploadedFile.file_name,
            status: "processing"
          });
        }

        // Mark 207 "failed" files as error immediately
        // Use multiple matching strategies to handle file_name encoding issues
        for (const failedFile of failed) {
          const matched =
            batch.find((b) => b.file_name === failedFile.file_name) ||
            batch.find(
              (b) =>
                failedFile.file_name?.includes(b.file_name) ||
                b.file_name?.includes(failedFile.file_name)
            ) ||
            // Last resort: find any unaccounted batch file
            batch.find((b) => !accountedTempIds.has(b.temp_id));

          if (matched) {
            accountedTempIds.add(matched.temp_id);
            // Record partial upload failure for retry
            failedFilesRef.current.push({
              temp_id: matched.temp_id,
              file_name: matched.file_name,
              error_stage: "upload"
            });
            sendMsg(JSON.stringify({
              action: "append",
              payload: [{
                temp_id: matched.temp_id,
                status: "error",
                error_message: failedFile.error || "Upload failed for this file"
              }]
            }));
            onFileFinished(job_id);
          }
        }

        // any batch file not in uploaded OR failed arrays
        // gets marked as error so it never stays stuck on "Computing..."
        // This handles silent server-side failures where a file is simply omitted
        for (const batchFile of batch) {
          if (!accountedTempIds.has(batchFile.temp_id)) {
            console.warn("File never accounted for, marking error:", batchFile.file_name);
            failedFilesRef.current.push({
              temp_id: batchFile.temp_id,
              file_name: batchFile.file_name,
              error_stage: "upload"
            });
            sendMsg(JSON.stringify({
              action: "append",
              payload: [{
                temp_id: batchFile.temp_id,
                status: "error",
                error_message: "File was not processed by server — please retry"
              }]
            }));
            onFileFinished(job_id);
          }
        }

        if (mapped.length > 0) {
          sendMsg(JSON.stringify({ action: "append", payload: mapped }));

          // Persist uploaded file IDs so onClickGenerate can use them
          uploadedFilesRef.current = [
            ...uploadedFilesRef.current,
            ...mapped.map((m) => ({ file_name: m.file_name, document_id: m.file_id }))
          ];

          // Mark next batch as processing NOW — before awaiting processBatch
          // processBatch runs compute + read which takes 40+ seconds
          // Without this, queued files would show "Queued" the entire time
          if (nextBatch) {
            sendMsg(JSON.stringify({
              action: "append",
              payload: nextBatch.map((file) => ({
                temp_id: file.temp_id,
                status: "processing"
              }))
            }));
          }

          // AWAIT processBatch — Upload → Compute → Read must all finish
          // before next batch UPLOAD starts (sequential upload guarantee)
          const ids = mapped.map((m) => m.file_id);
          await processBatch(ids, job_id, mapped, sendMsg);
        } else if (nextBatch) {
          // No successful uploads in this batch but still need to advance
          sendMsg(JSON.stringify({
            action: "append",
            payload: nextBatch.map((file) => ({
              temp_id: file.temp_id,
              status: "processing"
            }))
          }));
        }

      } catch (e) {
        console.error("Upload batch exception:", e);

        const errMsg = !navigator.onLine ? "No internet connection"
          : e?.name === "AbortError" ? "Upload was cancelled"
            : e?.message || "Unexpected upload error";

        // Record entire batch as upload-failed for retry
        batch.forEach((file) => {
          failedFilesRef.current.push({
            temp_id: file.temp_id,
            file_name: file.file_name,
            error_stage: "upload"
          });
        });

        sendMsg(JSON.stringify({
          action: "append",
          payload: batch.map((file) => ({
            temp_id: file.temp_id,
            file_id: file.temp_id,
            status: "error",
            error_message: errMsg
          }))
        }));

        batch.forEach(() => onFileFinished(job_id));

        if (nextBatch) {
          sendMsg(JSON.stringify({
            action: "append",
            payload: nextBatch.map((file) => ({
              temp_id: file.temp_id,
              status: "processing"
            }))
          }));
        }
      }
    }

    // ===== AUTO-RETRY LOOP =====
    // After all initial batches finish, retry any failed files (up to MAX_RETRY_ATTEMPTS times).
    // Each retry round re-runs only the files that failed in the previous round.
    // The tracker total is extended so onFileFinished keeps working correctly.
    const sendMsg = makeSendMsg();

    for (let attempt = 1; attempt <= MAX_RETRY_ATTEMPTS; attempt++) {
      const toRetry = [...failedFilesRef.current];

      if (toRetry.length === 0) {
        console.log(`[Retry] No failed files to retry (attempt ${attempt}). Done.`);
        break;
      }

      console.log(`[Retry] Attempt ${attempt}/${MAX_RETRY_ATTEMPTS} — retrying ${toRetry.length} file(s)`);

      // Clear the list so this attempt populates it fresh if files fail again
      failedFilesRef.current = [];

      // Extend the tracker total to account for the retry files
      // (each retried file will call onFileFinished once more)
      processingTrackerRef.current.total += toRetry.length;
      processingTrackerRef.current.finished -= toRetry.length; // un-count their prior "done"

      // Reset processingComplete so the toast doesn't fire prematurely
      setProcessingComplete(false);
      message.destroy("processing-complete");

      await retryFailedFiles(toRetry, job_id, sendMsg);
    }

    return { job_id };
  };

  // Reopens results dialog for an already-processed job
  // Called from "Reopen Results" or "Generate Assessment" button
  const onClickGenerate = async (jobId) => {
    setLoading(true);

    // Use persisted document_ids from upload API response
    // fileList only contains raw browser File objects with no document_id
    const ids = uploadedFilesRef.current.map((f) => f.document_id).filter(Boolean);

    if (ids.length === 0) {
      customMessage.error("No uploaded files found. Please re-upload your files.");
      setLoading(false);
      return;
    }

    try {
      const response = await readContractClassification({
        file_ids: ids,
        job_id: jobId,
        user_id: user.username
      });
      console.log("read Contract Classification: ", response);

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
                    payload: { result_json: response, jobId, userId: user.username }
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
      if (error.name === "AbortError") {
        customMessage.warning("Generate request cancelled.");
      } else {
        customMessage.error("Generate Review table failed.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleBase64Upload = async (base64File) => {
    setLoading(true);
    try {
      await uploadAndDigitize(base64File);
      message.success("Processing started");
    } catch (err) {
      console.error(err);
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
        if (!isFileDigitized) {
          abortControllerHandle();
          clearIntervalHandle();
          onBack();
        }
        setProtocolId(null);
        setIsFileDigitized(false);
        setFileList([]);
        setDataSource([]);
        setProcessingComplete(false);
        setJobId(null);
        uploadedFilesRef.current = [];
        failedFilesRef.current = [];
        base64FileMapRef.current = {};
      },
      onCancel() { console.log("Stay on page"); },
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
      <UploadSourceDocument />
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