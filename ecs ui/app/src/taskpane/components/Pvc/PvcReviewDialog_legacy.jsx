import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import ContractTable from "./ContractTable";
import { Spin } from "antd";

const PvcReviewDialog = () => {
  const [data, setData] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [userId, setUserId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [existingVersion, setExistingVersion] = useState(false);
  const [total, setTotal] = useState(0);
  const [completed, setCompleted] = useState(0);
  const [error, setError] = useState(null);

  const completedSetRef = useRef(new Set());
  const totalRef = useRef(0);

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

  useEffect(() => {
    Office.onReady().then(() => {
      Office.context.ui.addHandlerAsync(
        Office.EventType.DialogParentMessageReceived,
        (arg) => {
          const msg = JSON.parse(arg.message);

          // ================= INIT =================
          if (msg.action === "init") {
            const { result_json, jobId, userId, existingVersion, totalFiles } = msg.payload;

            const safeTotal = totalFiles || (result_json ? result_json.length : 0);

            setData(result_json || []);
            setJobId(jobId);
            setUserId(userId);

            setTotal(safeTotal);
            totalRef.current = safeTotal;

            setCompleted(0);
            completedSetRef.current = new Set();

            if (existingVersion) {
              setExistingVersion(existingVersion);
            }
          }

          // ================= APPEND =================
          if (msg.action === "append") {
            const newData = Array.isArray(msg.payload)
              ? msg.payload
              : [msg.payload];

            setData((prev) => {
              const updated = [...prev];

              newData.forEach((item) => {
                let index = updated.findIndex(
                  (i) =>
                    i.file_id === item.file_id ||
                    i.file_id === item.temp_id ||
                    i.temp_id === item.temp_id
                );

                if (index !== -1) {
                  updated[index] = {
                    ...updated[index],
                    ...item,
                    file_id: item.file_id || updated[index].file_id,
                    temp_id: updated[index].temp_id || item.temp_id
                  };
                } else {
                  updated.push(item);
                }

                if (item.status === "done" || item.status === "error") {
                  completedSetRef.current.add(item.temp_id);
                }
              });

              return updated;
            });

            const currentCompleted = completedSetRef.current.size;

            setCompleted(currentCompleted);
            setLoading(false);

            // FINAL FIX: handle missing / failed rows
            if (totalRef.current > 0 && currentCompleted >= totalRef.current) {

              // FORCE FIX stuck "Computing..."
              setData((prev) =>
                prev.map((row) => {
                  if (!completedSetRef.current.has(row.temp_id)) {
                    return {
                      ...row,
                      status: "error",
                      error_message: "Processing failed"
                    };
                  }
                  return row;
                })
              );

              // notify parent
              Office.context.ui.messageParent(
                JSON.stringify({
                  action: "allCompleted",
                  payload: { jobId }
                })
              );
            }
          }

          // ================= ERROR =================
          if (msg.action === "error") {
            setError(msg.payload?.message || "Something went wrong");
            setLoading(false);

            Office.context.ui.messageParent(
              JSON.stringify({
                action: "allCompleted",
                payload: { jobId }
              })
            );
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

  return (
    <>
      <Spin spinning={loading && data.length === 0} tip="Loading, please wait...">
        <ContractTable
          data={data}
          jobId={jobId}
          userId={userId}
          existingVersion={existingVersion}
          onSubmit={handleSubmit}
        />
      </Spin>

      {error && (
        <div
          style={{
            padding: 16,
            textAlign: "center",
            color: "#ff4d4f",
            fontSize: 13
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