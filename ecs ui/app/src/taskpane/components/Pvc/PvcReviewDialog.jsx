import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import ContractTable from "./ContractTable";
import { Spin, Progress } from "antd";

const PvcReviewDialog = () => {
  const [data, setData] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [userId, setUserId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [existingVersion, setExistingVersion] = useState(false);
  const [total, setTotal] = useState(0);
  const [completed, setCompleted] = useState(0);
  const [error, setError] = useState(null);
  const [jobStatus, setJobStatus] = useState("PROCESSING");
  const [statusMessage, setStatusMessage] = useState("Processing files...");
  const [notShowProgress, setNotShowProgress] = useState(false);

  const completedSetRef = useRef(new Set());
  const totalRef = useRef(0);
  const jobIdRef = useRef(null);       // avoids the stale-closure jobId problem
  const finalizedRef = useRef(false);  // ensures we finalize / fire allCompleted only once

  const handleSubmit = (modifiedData) => {
    if (Office.context.ui) {
      Office.context.ui.messageParent(
        JSON.stringify({
          action: "close",
          payload: modifiedData,
        })
      );
    }
  };

  // Merge a batch of result rows into `data` and update the completed set.
  // NOTE: this no longer decides completion — that is driven by job status.
  const mergeResults = (payload) => {
    const newData = Array.isArray(payload) ? payload : [payload];

    setData((prev) => {
      const updated = [...prev];

      newData.forEach((item) => {
        const index = updated.findIndex(
          (i) =>
            i.file_id === item.file_id ||
            i.file_id === item.temp_id ||
            i.temp_id === item.temp_id
        );

        const existing = index >= 0 ? updated[index] : {};
        const mergedItem = {
          ...existing,
          ...item,
          status: item.status || "done",
          file_id: item.file_id || existing.file_id || null,
          temp_id: existing.temp_id || item.temp_id || null,
        };

        if (index !== -1) {
          updated[index] = mergedItem;
        } else {
          updated.push(mergedItem);
        }

        if (mergedItem.status === "done" || mergedItem.status === "error") {
          completedSetRef.current.add(mergedItem.temp_id || mergedItem.file_id);
        }
      });

      return updated;
    });

    setCompleted((prev) => Math.max(prev, completedSetRef.current.size));
    setLoading(false);
  };

  // Finalize the UI when the backend reports a terminal status.
  // Runs at most once per job.
  const finalize = (terminalStatus) => {
    if (finalizedRef.current) return;
    finalizedRef.current = true;

    if (terminalStatus === "COMPLETED") {
      // Any row that never received a result is a genuine failure now.
      setData((prev) =>
        prev.map((row) => {
          const done = completedSetRef.current.has(row.temp_id || row.file_id);
          if (!done && row.status !== "done") {
            return {
              ...row,
              status: "error",
              error_message: row.error_message || "Processing failed",
            };
          }
          return row;
        })
      );
      setCompleted(totalRef.current);

      // Tell the parent it can stop polling. jobIdRef avoids the stale-closure null.
      Office.context.ui.messageParent(
        JSON.stringify({ action: "allCompleted", payload: { jobId: jobIdRef.current } })
      );
    } else if (terminalStatus === "FAILED") {
      setData((prev) =>
        prev.map((row) =>
          row.status === "done"
            ? row
            : { ...row, status: "error", error_message: row.error_message || "Processing failed" }
        )
      );
      setError("Job processing failed. Please retry.");
      // Parent independently handles FAILED via its own poll, so we don't send allCompleted here.
    }
  };

  useEffect(() => {
    Office.onReady().then(() => {
      Office.context.ui.addHandlerAsync(
        Office.EventType.DialogParentMessageReceived,
        (arg) => {
          const msg = JSON.parse(arg.message);

          // ================= INIT =================
          if (msg.action === "init") {
            const { result_json, jobId, userId, existingVersion, totalFiles, notShowProgress } = msg.payload;

            const safeTotal = totalFiles || (result_json ? result_json.length : 0);

            setData(result_json || []);
            setJobId(jobId);
            setUserId(userId);
            jobIdRef.current = jobId;
            finalizedRef.current = false;

            setTotal(safeTotal);
            totalRef.current = safeTotal;

            setCompleted(0);
            completedSetRef.current = new Set();
            setJobStatus("PROCESSING");
            setStatusMessage("Processing files...");
            setError(null);

            if (existingVersion) {
              setExistingVersion(existingVersion);
            }

            setNotShowProgress(notShowProgress);
          }

          // ================= UPDATE RESULTS =================
          // Just merge rows into the table. Completion is NOT decided here.
          if (msg.action === "updateResults") {
            mergeResults(msg.payload);
          }

          // ================= UPDATE STATUS =================
          // Single source of truth for completion: the backend job status,
          // forwarded by the parent on every poll.
          if (msg.action === "updateStatus") {
            const { status, totalFiles, processedFiles, message } = msg.payload || {};

            if (status) setJobStatus(status);
            if (message) setStatusMessage(message);

            if (typeof totalFiles === "number" && totalFiles > 0) {
              setTotal(totalFiles);
              totalRef.current = totalFiles;
            }
            if (typeof processedFiles === "number") {
              setCompleted((prev) => Math.max(prev, processedFiles));
            }

            if (status === "COMPLETED") {
              finalize("COMPLETED");
            } else if (status === "FAILED") {
              finalize("FAILED");
            }
            // PROCESSING / PENDING / anything transient -> do nothing, keep waiting.
          }

          // ================= APPEND (Legacy compatibility) =================
          // Same as updateResults: merge only, no count-based completion.
          if (msg.action === "append") {
            mergeResults(msg.payload);
          }

          // ================= ERROR =================
          if (msg.action === "error") {
            setError(msg.payload?.message || "Something went wrong");
            setLoading(false);

            if (!finalizedRef.current) {
              finalizedRef.current = true;
              Office.context.ui.messageParent(
                JSON.stringify({ action: "allCompleted", payload: { jobId: jobIdRef.current } })
              );
            }
          }
        }
      );

      setTimeout(() => {
        Office.context.ui.messageParent(
          JSON.stringify({ action: "ready" })
        );
      }, 100);
    });
  }, []);

  const progressPercent =
    total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  const showProgress =
    !notShowProgress &&
    total > 0 &&
    (jobStatus === "PROCESSING" || jobStatus === "PENDING" || jobStatus === "COMPLETED");

  return (
    <>
      <Spin spinning={loading && data.length === 0} tip="Loading, please wait...">
        {/* Progress indicator */}
        {showProgress && (
          <div style={{ padding: "16px", background: "#f0f5ff", borderBottom: "1px solid #d9d9d9" }}>
            <div style={{ marginBottom: 8, fontSize: 14, color: "#595959" }}>
              {statusMessage}
            </div>
            <Progress
              percent={progressPercent}
              status={jobStatus === "COMPLETED" ? "success" : "active"}
              format={() => `${Math.min(completed, total)} / ${total}`}
            />
          </div>
        )}

        {/* Results table */}
        <ContractTable
          data={data}
          jobId={jobId}
          userId={userId}
          existingVersion={existingVersion}
          onSubmit={handleSubmit}
          disabled={jobStatus === "COMPLETED" ? false : true}
        />
      </Spin>

      {/* Error message */}
      {error && (
        <div
          style={{
            padding: 16,
            textAlign: "center",
            color: "#ff4d4f",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}
    </>
  );
};

export default PvcReviewDialog;

Office.onReady(() => {
  const container = document.getElementById("pvc_review_container");
  if (container) {
    const root = createRoot(container);
    root.render(<PvcReviewDialog />);
  } else {
    console.error("#pvc_review_container not found");
  }
});
 