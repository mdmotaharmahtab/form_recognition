import React, { useEffect, useState } from "react";
import {
  Table,
  Input,
  Tag,
  Space,
  Tooltip,
  Card,
  Button,
  Collapse,
  Spin,
  Modal
} from "antd";
import {
  LikeOutlined,
  LikeFilled,
  DislikeOutlined,
  DislikeFilled
} from "@ant-design/icons";
import styled from "styled-components";
import { getConfidenceStyle } from "../../taskpane";
import { contractClassificationFeedback, contractFeatureToggle, exportDocument } from "../../../services/ccmApiService";
import { downloadDocxFromBase64 } from "../../../services/functions";
import { marked } from "marked";
import DOMPurify from 'dompurify';
import * as mammoth from "mammoth";
import ConfidenceChip from "./ConfidenceChip";

const { Panel } = Collapse;

export const StyledTableWrapper = styled.div`
  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
    line-height: 1.2;
  }

  /* ── Done: default blue gradient ── */
  .ant-table-tbody > tr > td {
    background: linear-gradient(
      150deg,
      rgba(235, 240, 255, 1) 25%,
      rgba(225, 235, 255, 1) 50%,
      rgba(215, 230, 255, 1) 100%
    ) !important;
    border: 1px solid #bfd3f2;
    color: #2c4c91;
    font-size: 11px;
    padding: 6px 12px;
    line-height: 1;
  }

  /* ── Pending: muted grey, faded, blocked ── */
  .ant-table-tbody > tr.row-pending > td {
    background: rgba(210, 213, 220, 0.25) !important;
    border-color: #e0e0e0 !important;
    color: #bbb !important;
    pointer-events: none;
    cursor: not-allowed;
  }
  .ant-table-tbody > tr.row-pending {
    opacity: 0.5;
  }

  /* ── Processing: shimmer wave across the entire row ── */
  .ant-table-tbody > tr.row-processing > td {
    background: linear-gradient(
      90deg,
      rgba(22, 119, 255, 0.05) 0%,
      rgba(22, 119, 255, 0.15) 40%,
      rgba(22, 119, 255, 0.05) 80%
    ) !important;
    background-size: 1200px 100% !important;
    animation: shimmerWave 1.8s linear infinite !important;
    border-color: rgba(22, 119, 255, 0.2) !important;
    color: #1a3a6b !important;
    pointer-events: none;
    cursor: progress;
  }

  /* ── Error: soft red, left accent ── */
  .ant-table-tbody > tr.row-error > td {
    background: rgba(255, 77, 79, 0.06) !important;
    border-color: rgba(255, 77, 79, 0.18) !important;
    color: #a8071a !important;
  }
  .ant-table-tbody > tr.row-error > td:first-child {
    border-left: 3px solid #ff4d4f !important;
  }

  @keyframes shimmerWave {
    0%   { background-position: -600px 0; }
    100% { background-position: 600px 0; }
  }
`;

const StyledButton = styled(Button)`
  background: #426BBA !important;
  color: white !important;
  font-weight: 600;
  font-size: 14px;
  border: none;
  border-radius: 1rem;
  box-shadow: 0 2px 6px rgba(66, 107, 186, 0.2);
  padding: 4px 16px;

  &:hover {
    background: #365aa3 !important;
    color: white !important;
  }
`;

const StyledModal = styled(Modal)`
  .ant-modal-close {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .ant-modal-close-x {
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

  .ant-modal-close .anticon {
    display: flex;
    align-items: center;
    justify-content: center;
  }
`;

const chunkArray = (arr, size) => {
  const res = [];
  for (let i = 0; i < arr.length; i += size) {
    res.push(arr.slice(i, i + size));
  }
  return res;
};

const questionMap = {
  safety_reporting_language:
    "Does the contract contain safety reporting language?",
  safety_reporting_methodology:
    "Does the contract contain the methodology for how safety information should be reported to Otsuka?",
  pv_subcontracting_restriction:
    "Does the contract contain subcontracting language that notes PV activities should not be subcontracted without written approval from Otsuka?",
  audit_inspection_rights:
    "Does the contract contain audit and inspection language that the third party can be audited by Otsuka or inspected by relevant authority?"
};

const METADATA_KEY_ORDER = [
  "Organization",
  "Contract_Title",
  "Contract_Class",
  "External_Party_Name",
  "External Party Type",
  "External_Party_Role",
  "Territory of Activity",
  "Effective_Start_Date",
  "Effective_End_Date",
  "Product_Name",
  "Study_ID",
  "IT_System_Name",
  "Safety_Reporting_Language",
  "Safety_Reporting_Methodology",
  "PV_Subcontracting_Restriction",
  "Audit_Inspection_Language"
];

const ContractTable = ({ data, jobId, userId, onSubmit, disabled }) => {
  const [contracts, setContracts] = useState([]);
  const [reviewState, setReviewState] = useState({});
  const [expandedRowKeys, setExpandedRowKeys] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(null);
  const [loading, setLoading] = useState(false);

const [previewModal, setPreviewModal] = useState({
  open: false,
  fileId: null,
  fileName: null,
  base64Docx: null,
  previewHtml: null,
  pdfBlobUrl: null,
  isPdf: false,
  loadingPreview: false,
  previewError: null,
  downloading: false
});

  useEffect(() => {
    if (data?.length) {
      setContracts(data);

      const initialReview = {};
      data.forEach((item) => {
        initialReview[item.file_id] = {
          feedback: item.feedback ?? null,
          metadata_feedback: Object.fromEntries(
            Object.entries(item.metadata || {}).map(([key, value]) => [
              key,
              value?.is_liked === true
                ? true
                : value?.is_liked === false
                  ? false
                  : null
            ])
          ),
          classification_comment: item.classification_comment || "",
          extraction_comment: item.extraction_comment || ""
        };
      });

      setReviewState(initialReview);
    }
  }, [data]);

  const updateReview = (fileId, field, value) => {
    setReviewState((prev) => ({
      ...prev,
      [fileId]: {
        ...prev[fileId],
        [field]: value
      }
    }));
  };

  const sendContractFeedback = async ({ fileId, category, message, jobId }) => {
    try {
      setLoading(true);
      await contractClassificationFeedback({
        file_id: fileId,
        feedback_category: category,
        feedback_message: message,
        job_id: jobId,
        user_id: userId
      });
    } catch (error) {
      console.error("Feedback API failed", error);
    } finally {
      setLoading(false);
    }
  };

  const handleClassificationFeedback = async (fileId, message) => {
    const previous = reviewState[fileId]?.classic_feedback || "";
    const newValue = message?.trim() || "";
    if (!newValue) return;
    if (previous === newValue) return;

    setReviewState((prev) => ({
      ...prev,
      [fileId]: { ...prev[fileId], classic_feedback: newValue }
    }));

    await sendContractFeedback({ fileId, category: "classification", message: newValue, jobId });
  };

  const handleExtractionFeedback = async (fileId, message) => {
    setReviewState((prev) => ({
      ...prev,
      [fileId]: { ...prev[fileId], extraction_feedback: message }
    }));

    await sendContractFeedback({ fileId, category: "extraction", message, jobId });
  };

  const updatePVFeedback = async (fileId, value) => {
    const newValue = reviewState[fileId]?.feedback === value ? null : value;

    setReviewState((prev) => ({
      ...prev,
      [fileId]: { ...prev[fileId], feedback: newValue }
    }));

    try {
      setLoading(true);
      await contractFeatureToggle({
        file_id: fileId,
        metadata_key_name: "feedback",
        is_liked_flag: newValue,
        job_id: jobId,
        user_id: userId
      });
    } catch (error) {
      console.error("PV feedback API failed", error);
    } finally {
      setLoading(false);
    }
  };

  const updateMetadataFeedback = async (fileId, key, value) => {
    const newValue = reviewState[fileId]?.metadata_feedback?.[key] === value ? null : value;

    setReviewState((prev) => ({
      ...prev,
      [fileId]: {
        ...prev[fileId],
        metadata_feedback: { ...prev[fileId].metadata_feedback, [key]: newValue }
      }
    }));

    try {
      setLoading(true);
      await contractFeatureToggle({
        file_id: fileId,
        metadata_key_name: key,
        is_liked_flag: newValue,
        job_id: jobId,
        user_id: userId
      });
    } catch (error) {
      console.error("Metadata feedback API failed", error);
    } finally {
      setLoading(false);
    }
  };

  const base64ToArrayBuffer = (base64) => {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  };

  const handleOpenPreview = async (record) => {
  setPreviewModal({
  open: true,
  fileId: record.file_id,
  fileName: record.file_name,
  base64Docx: null,
  previewHtml: null,
  pdfBlobUrl: null,
  isPdf: false,
  loadingPreview: true,
  previewError: null,
  downloading: false
});

  try {
    const res = await exportDocument({ file_id: record.file_id, user_id: userId });
    const payload = res.response ?? res;
    const base64 = payload.base64_encoded_docx;
    const s3Key = payload.s3_object_key || "";
    const fileType = s3Key.split("/").pop() || record.file_name || "";
const isPdf = fileType.toLowerCase().endsWith(".pdf");
const fileName = record.file_name.replace(/\.[^.]+$/, "") + (isPdf ? ".pdf" : ".docx");

    if (isPdf) {
      const blob = new Blob([Uint8Array.from(atob(base64), c => c.charCodeAt(0))], { type: "application/pdf" });
      const pdfBlobUrl = URL.createObjectURL(blob);
      setPreviewModal((prev) => ({
        ...prev,
        base64Docx: base64,
        fileName,
        isPdf: true,
        previewHtml: null,
        pdfBlobUrl,
        loadingPreview: false
      }));
    } else {
      const arrayBuffer = base64ToArrayBuffer(base64);
      const { value: html } = await mammoth.convertToHtml({ arrayBuffer });
      setPreviewModal((prev) => ({
        ...prev,
        base64Docx: base64,
        fileName,
        isPdf: false,
        previewHtml: html,
        pdfBlobUrl: null,
        loadingPreview: false
      }));
    }
  } catch (error) {
    console.error("Preview fetch/conversion failed", error);
    setPreviewModal((prev) => ({
      ...prev,
      loadingPreview: false,
      previewError: "Failed to load contract preview. You can still download the file."
    }));
  }
};

  const handleClosePreview = () => {
    setPreviewModal({
      open: false,
      fileId: null,
      fileName: null,
      base64Docx: null,
      previewHtml: null,
      pdfBlobUrl: null,
      loadingPreview: false,
      previewError: null,
      downloading: false
    });
  };

  const handleDownloadFromPreview = async () => {
    if (previewModal.base64Docx) {
  const isPdf = previewModal.isPdf;
  if (isPdf) {
    const blob = new Blob(
      [Uint8Array.from(atob(previewModal.base64Docx), c => c.charCodeAt(0))],
      { type: "application/pdf" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = previewModal.fileName.replace(/\.[^.]+$/, "") + ".pdf";
    a.click();
    URL.revokeObjectURL(url);
  } else {
    const docxName = previewModal.fileName.replace(/\.[^.]+$/, "") + ".docx";
    downloadDocxFromBase64(previewModal.base64Docx, docxName);
  }
  return;
}
    setPreviewModal((prev) => ({ ...prev, downloading: true }));
    try {
      const res = await exportDocument({ file_id: previewModal.fileId, user_id: userId });
      const fileName = previewModal.fileName;
      downloadDocxFromBase64(res.base64_encoded_docx, fileName);
    } catch (error) {
      console.error("Export document API failed", error);
    } finally {
      setPreviewModal((prev) => ({ ...prev, downloading: false }));
    }
  };

  const handleNext = () => {
    if (currentIndex < contracts.length - 1) {
      const next = currentIndex + 1;
      setCurrentIndex(next);
      setExpandedRowKeys([contracts[next].file_id]);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      const prev = currentIndex - 1;
      setCurrentIndex(prev);
      setExpandedRowKeys([contracts[prev].file_id]);
    }
  };

  const handleSubmitReview = () => {
    const processedData = contracts.map((contract) => {
      const review = reviewState[contract.file_id] || {};
      const metadata = {};

      if (contract.metadata) {
        Object.entries(contract.metadata).forEach(([key, value]) => {
          metadata[key] = {
            ...value,
            is_liked: review.metadata_feedback?.[key] ?? value.is_liked
          };
        });
      }

      return {
        ...contract,
        classification_comment: review.classification_comment || "",
        extraction_comment: review.extraction_comment || "",
        feedback: review.feedback ?? null,
        metadata
      };
    });

    onSubmit(processedData);
  };

  const formatMarkdown = (text) => {
    if (!text) return "";
    const cleaned = text
      .replace(/\u00A0/g, " ")
      .replace(/^\s+/gm, "")
      .replace(/•/g, "-")
      .replace(/\n{2,}/g, "\n\n")
      .replace(/\\\*/g, "*");
    return marked.parse(cleaned, { gfm: true, breaks: true });
  };

  const renderExpandedRow = (record) => {
    console.log("record: ", record)
    const review = reviewState[record.file_id] || {};
    const metadataEntries = Object.entries(record.metadata || {});
    const sortedMetadataEntries = [
      ...metadataEntries.filter(([key]) => METADATA_KEY_ORDER.includes(key))
        .sort(([a], [b]) => METADATA_KEY_ORDER.indexOf(a) - METADATA_KEY_ORDER.indexOf(b)),
      ...metadataEntries.filter(([key]) => !METADATA_KEY_ORDER.includes(key))
    ];
    const metadataRows = chunkArray(sortedMetadataEntries, 3);

    return (
      <Spin spinning={loading}>
        <div>
          <Card bodyStyle={{ padding: "6px 10px" }} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span>
                Classification (PV Related or Not):{" "}
                <b>
                  {record.is_pv === true ? "PV" : record.is_pv === false ? "Non-PV" : "Unclassified"}
                </b>
              </span>
              <Space size="small">
                {review.feedback === true ? (
                  <LikeFilled onClick={() => updatePVFeedback(record.file_id, true)} />
                ) : (
                  <LikeOutlined onClick={() => updatePVFeedback(record.file_id, true)} />
                )}
                {review.feedback === false ? (
                  <DislikeFilled onClick={() => updatePVFeedback(record.file_id, false)} />
                ) : (
                  <DislikeOutlined onClick={() => updatePVFeedback(record.file_id, false)} />
                )}
                <ConfidenceChip score={record?.pv_confidence} />
              </Space>
            </div>
          </Card>

          {metadataRows.map((row, idx) => (
            <div key={idx} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              {row.map(([key, value]) => {
                const { percentage } = getConfidenceStyle(value?.confidence_score);
                return (
                  <Card key={key} style={{ flex: 1 }} bodyStyle={{ padding: "4px 8px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                      <span>
                        <b>{questionMap[key] || key.replace(/_/g, " ")}:</b>{" "}
                        {value?.metadata_key}
                      </span>
                      <Space size="small">
                        {review.metadata_feedback?.[key] === true ? (
                          <LikeFilled onClick={() => updateMetadataFeedback(record.file_id, key, true)} />
                        ) : (
                          <LikeOutlined onClick={() => updateMetadataFeedback(record.file_id, key, true)} />
                        )}
                        {review.metadata_feedback?.[key] === false ? (
                          <DislikeFilled onClick={() => updateMetadataFeedback(record.file_id, key, false)} />
                        ) : (
                          <DislikeOutlined onClick={() => updateMetadataFeedback(record.file_id, key, false)} />
                        )}
                        <ConfidenceChip score={percentage} />
                      </Space>
                    </div>
                  </Card>
                );
              })}
            </div>
          ))}

          <Card bodyStyle={{ padding: "6px 10px" }} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "11px" }}>
              <span><b>Original Language: </b>{record.orig_language || "-"}</span>
              <Button
                size="small"
                style={{ backgroundColor: "#426bba", borderColor: "#426bba", color: "#fff" }}
                onClick={() => handleOpenPreview(record)}
              // disabled={record.orig_language === "English"}
              >
                Preview Contract
              </Button>
            </div>
          </Card>

          <Card bodyStyle={{ padding: "8px 12px" }} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12 }}><b>Reason:</b></div>
            <div style={{ fontSize: 11, marginTop: 4, whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
              <Collapse>
                <Panel header="Reason" key="1">
                  <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(formatMarkdown(record.reason)) }} />
                </Panel>
              </Collapse>
            </div>
          </Card>

          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12 }}>
            <div style={{ width: "65%" }}>
              <div style={{ fontSize: 12, marginBottom: 4 }}>Classification Feedback</div>
              <Input.TextArea
                rows={2}
                value={review.classification_comment}
                onChange={(e) => updateReview(record.file_id, "classification_comment", e.target.value)}
                onBlur={(e) => handleClassificationFeedback(record.file_id, e.target.value)}
                style={{ marginBottom: 10 }}
              />
              <div style={{ fontSize: 12, marginBottom: 4 }}>Extraction Feedback</div>
              <Input.TextArea
                rows={2}
                value={review.extraction_comment}
                onChange={(e) => updateReview(record.file_id, "extraction_comment", e.target.value)}
                onBlur={(e) => handleExtractionFeedback(record.file_id, e.target.value)}
              />
            </div>
            <Space>
              {currentIndex > 0 && (
                <StyledButton onClick={handlePrevious}>Previous Contract</StyledButton>
              )}
              {currentIndex < contracts.length - 1 && (
                <StyledButton type="primary" onClick={handleNext}>Next Contract</StyledButton>
              )}
            </Space>
          </div>
        </div>
      </Spin>
    );
  };

  // Skeleton shimmer bar — shown in cells while row is processing or pending
  const SkeletonBar = ({ width = 80 }) => (
    <span style={{
      display: "inline-block",
      width,
      height: 10,
      borderRadius: 4,
      background: "linear-gradient(90deg, #dce8ff 25%, #b8d0f7 50%, #dce8ff 75%)",
      backgroundSize: "400px 100%",
      animation: "skeletonShimmer 1.6s linear infinite",
      verticalAlign: "middle"
    }} />
  );

  const columns = [
    {
      title: "File Name",
      dataIndex: "file_name",
      render: (text, record) => {
        const isBlocked = record.status === "pending" || record.status === "processing";
        return (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: isBlocked ? "not-allowed" : "pointer"
            }}
            onClick={() => {
              if (isBlocked) return;
              setExpandedRowKeys([record.file_id]);
              setCurrentIndex(contracts.findIndex((c) => c.file_id === record.file_id));
            }}
          >
            {/* File name always visible so user can see which file it is */}
            <span style={{ fontSize: 11 }}>{text}</span>

            {/* Processing: animated "Computing..." pill */}
            {record.status === "processing" && (
              <span style={{
                fontSize: 10,
                color: "#1677ff",
                background: "rgba(22,119,255,0.08)",
                border: "1px solid rgba(22,119,255,0.2)",
                borderRadius: 20,
                padding: "1px 8px",
                whiteSpace: "nowrap",
                fontWeight: 600
              }}>
                Computing…
              </span>
            )}

            {/* Pending: muted "Queued" pill */}
            {record.status === "pending" && (
              <span style={{
                fontSize: 10,
                color: "#aaa",
                background: "rgba(200,200,210,0.2)",
                border: "1px solid #ddd",
                borderRadius: 20,
                padding: "1px 8px",
                whiteSpace: "nowrap"
              }}>
                Queued
              </span>
            )}

            {/* Error: red pill with tooltip showing exact reason */}
            {record.status === "error" && (
              <Tooltip
                title={record.error_message || "Processing failed. Please try re-uploading this file."}
                placement="top"
              >
                <span style={{
                  fontSize: 10,
                  color: "#ff4d4f",
                  background: "rgba(255,77,79,0.08)",
                  border: "1px solid rgba(255,77,79,0.25)",
                  borderRadius: 20,
                  padding: "1px 8px",
                  cursor: "help",
                  whiteSpace: "nowrap",
                  fontWeight: 600
                }}>
                  ⚠ Failed ⓘ
                </span>
              </Tooltip>
            )}
          </div>
        );
      }
    },

    {
      title: "PV Status",
      dataIndex: "is_pv",
      render: (_, record) => {
        if (record.status === "processing") return <SkeletonBar width={60} />;
        if (record.status === "pending") return <SkeletonBar width={50} />;
        if (record.status === "error") return <span style={{ color: "#ffb3b3" }}>—</span>;
        if (record.is_pv === true) return <Tag color="red">PV</Tag>;
        if (record.is_pv === false) return <Tag>Non-PV</Tag>;
        return <Tag color="default">Unclassified</Tag>;
      }
    },

    {
      title: "Confidence Score",
      dataIndex: "pv_confidence",
      align: "center",
      render: (score, record) => {
        if (record.status === "processing") return <SkeletonBar width={36} />;
        if (record.status === "pending") return <SkeletonBar width={28} />;
        if (record.status === "error") return <span style={{ color: "#ffb3b3" }}>—</span>;
        return <ConfidenceChip score={score} />;
      }
    }
  ];

  return (
    <>
      <style>{`
        @keyframes skeletonShimmer {
          0%   { background-position: -400px 0; }
          100% { background-position:  400px 0; }
        }
      `}</style>

      <StyledTableWrapper>
        <Table
          rowKey="file_id"
          columns={columns}
          dataSource={contracts}
          pagination={false}
          rowClassName={(record) => {
            if (record.status === "pending") return "row-pending";
            if (record.status === "processing") return "row-processing";
            if (record.status === "error") return "row-error";
            return "row-done";
          }}
          expandable={{
            expandedRowRender: renderExpandedRow,
            expandedRowKeys,
            onExpand: (expanded, record) => {
              if (record.status === "pending" || record.status === "processing") return;
              setExpandedRowKeys(expanded ? [record.file_id] : []);
              setCurrentIndex(
                expanded ? contracts.findIndex((c) => c.file_id === record.file_id) : null
              );
            }
          }}
        />
        <div style={{ marginTop: 16, textAlign: "right" }}>
          <StyledButton type="primary" disabled={disabled} onClick={handleSubmitReview}>
            Submit
          </StyledButton>
        </div>
      </StyledTableWrapper>

      <StyledModal
        open={previewModal.open}
        onCancel={handleClosePreview}
        title={
          <div
            style={{
              color: "#2c4c91",
              fontWeight: 600,
              fontSize: "14px",
              paddingRight: "40px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis"
            }}
            title={previewModal.fileName}
          >
            Contract Preview
            {previewModal.fileName
              ? ` — ${previewModal.fileName}`
              : ""}
          </div>
        }
        width={800}
        footer={[
          <Button
            key="download"
            loading={previewModal.downloading}
            style={{
              backgroundColor: "#426bba",
              borderColor: "#426bba",
              color: "#fff",
              borderRadius: "1rem",
              fontWeight: 600
            }}
            onClick={handleDownloadFromPreview}
          >
            Download Contract
          </Button>,
          <Button key="close" onClick={handleClosePreview} style={{ borderRadius: "1rem" }}>
            Close
          </Button>
        ]}
        bodyStyle={{ padding: "16px 24px", minHeight: 300 }}
      >
        {previewModal.loadingPreview && (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 300 }}>
            <Spin tip="Loading contract preview..." size="large" />
          </div>
        )}

        {!previewModal.loadingPreview && previewModal.previewError && (
          <div
            style={{
              background: "#fff2f0",
              border: "1px solid #ffccc7",
              borderRadius: 8,
              padding: "20px 24px",
              minHeight: 120,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              color: "#cf1322",
              fontSize: 13
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 10 }}>⚠️</div>
            <div>{previewModal.previewError}</div>
          </div>
        )}

        {!previewModal.loadingPreview && !previewModal.previewError && previewModal.pdfBlobUrl && (
          <iframe
            src={previewModal.pdfBlobUrl}
            width="100%"
            height="600px"
            style={{ border: "none", borderRadius: 8 }}
          />
        )}

        {!previewModal.loadingPreview && !previewModal.previewError && previewModal.previewHtml && (
          <div
            style={{
              background: "#fff",
              border: "1px solid #bfd3f2",
              borderRadius: 8,
              padding: "32px 40px",
              maxHeight: "65vh",
              overflowY: "auto",
              fontSize: 13,
              lineHeight: 1.7,
              color: "#1a1a2e",
              boxShadow: "inset 0 1px 4px rgba(66,107,186,0.06)"
            }}
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(previewModal.previewHtml) }}
          />
        )}
      </StyledModal>
    </>
  );
};

export default ContractTable;