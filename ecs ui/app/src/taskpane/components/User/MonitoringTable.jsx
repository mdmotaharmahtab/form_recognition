import React, { useState, useEffect } from "react";
import {
  Table,
  Button,
  message,
  Input,
  Space,
  Card,
  Tag,
  Collapse,
  Popover,
  Spin,
  Tooltip,
  List,
  Typography,
} from "antd";
import {
  LikeFilled,
  DislikeFilled,
  HistoryOutlined,
  UserOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import styled from "styled-components";
import { getConfidenceStyle } from "../../taskpane";
import {
  getAllAdminFeedback,
  getAllFeedback,
  postAdminFeedback,
} from "../../../services/ccmApiService";
import ConfidenceChip from "../Pvc/ConfidenceChip";

const { Panel } = Collapse;
const { Text } = Typography;

// ─── Styled Components ────────────────────────────────────────────────────────

const StyledTableWrapper = styled.div`
  width: 100%;
  /* Let the wrapper scroll vertically so expanded rows are fully visible */
  overflow-y: auto;

  /* Prevent antd from clipping expanded row content */
  .ant-table {
    overflow: visible !important;
  }
  .ant-table-container {
    overflow: visible !important;
  }
  .ant-table-content {
    overflow: visible !important;
  }

  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 12px;
    white-space: nowrap;
    line-height: 1.2;
  }

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
    word-break: break-word;
    line-height: 1;
  }

  .ant-table-expanded-row > td {
    background: #f0f4ff !important;
    padding: 12px 16px !important;
    /* Allow expanded content to grow freely */
    overflow: visible !important;
  }
`;

const StyledButton = styled(Button)`
  background: #426bba !important;
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

// ─── Constants ────────────────────────────────────────────────────────────────

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
  "Audit_Inspection_Language",
];

const questionMap = {
  safety_reporting_language:
    "Does the contract contain safety reporting language?",
  safety_reporting_methodology:
    "Does the contract contain the methodology for how safety information should be reported to Otsuka?",
  pv_subcontracting_restriction:
    "Does the contract contain subcontracting language that notes PV activities should not be subcontracted without written approval from Otsuka?",
  audit_inspection_rights:
    "Does the contract contain audit and inspection language that the third party can be audited by Otsuka or inspected by relevant authority?",
};

const chunkArray = (arr, size) => {
  const res = [];
  for (let i = 0; i < arr.length; i += size) res.push(arr.slice(i, i + size));
  return res;
};

const formatTime = (timeStr) => {
  if (!timeStr) return "—";
  try {
    return new Date(timeStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return timeStr;
  }
};

// ─── Feedback History Popover ─────────────────────────────────────────────────

const FeedbackHistoryPopover = ({ fileId }) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState([]);

  const fetchHistory = async () => {
    // if (history.length > 0) return; // already loaded
    try {
      setLoading(true);

      const response = await getAllAdminFeedback({ file_id: fileId })
      setHistory(response?.result || []);
    } catch (err) {
      console.error("Failed to fetch feedback history", err);
      message.error("Failed to load feedback history");
    } finally {
      setLoading(false);
    }
  };

  const handleOpenChange = (visible) => {
    setOpen(visible);
    if (visible) fetchHistory();
  };

  const popoverContent = (
    <div style={{ width: 500, maxHeight: 280, overflowY: "auto" }}>
      {loading ? (
        <div style={{ textAlign: "center", padding: "16px 0" }}>
          <Spin size="small" />
        </div>
      ) : history.length === 0 ? (
        <div style={{ textAlign: "center", color: "#bbb", fontSize: 12, padding: "12px 0" }}>
          No feedback history yet
        </div>
      ) : (
        <List
          size="small"
          dataSource={history}
          renderItem={(item) => (
            <List.Item style={{ padding: "8px 0", borderBottom: "1px solid #e8eef8" }}>
              <div style={{ width: "100%" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <UserOutlined style={{ color: "#426bba", fontSize: 11 }} />
                  <Text style={{ fontSize: 11, fontWeight: 600, color: "#2c4c91" }}>
                    {item.user}
                  </Text>
                </div>
                <div style={{ fontSize: 11, color: "#444", marginBottom: 4, paddingLeft: 17 }}>
                  {item.feedback}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, paddingLeft: 17 }}>
                  <ClockCircleOutlined style={{ fontSize: 10, color: "#999" }} />
                  <Text style={{ fontSize: 10, color: "#999" }}>
                    {formatTime(item.time)}
                  </Text>
                </div>
              </div>
            </List.Item>
          )}
        />
      )}
    </div>
  );

  return (
    <Popover
      content={popoverContent}
      title={
        <span style={{ fontSize: 12, color: "#426bba", fontWeight: 600 }}>
          Feedback History
        </span>
      }
      trigger="click"
      open={open}
      onOpenChange={handleOpenChange}
      placement="topLeft"
    >
      <Tooltip title="View feedback history">
        <HistoryOutlined
          style={{
            fontSize: 14,
            color: "#426bba",
            cursor: "pointer",
            marginLeft: 6,
            verticalAlign: "middle",
          }}
        />
      </Tooltip>
    </Popover>
  );
};

// ─── FeedbackCell ─────────────────────────────────────────────────────────────

const FeedbackCell = ({ record, adminId, onSuccess }) => {
  const [feedback, setFeedback] = useState(record.admin_feedback || "");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!feedback?.trim()) {
      message.warning("Please enter feedback");
      return;
    }
    try {
      setSubmitting(true);
      await postAdminFeedback({
        admin_id: adminId,
        admin_feedback: feedback,
        file_id: record.file_id,
      });
      onSuccess?.(record.file_id, feedback, adminId);
      message.success("Feedback submitted successfully");
    } catch (error) {
      console.error(error);
      message.error("Failed to submit feedback");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Space.Compact style={{ width: "100%" }}>
      <Input.TextArea
        value={feedback}
        rows={3}
        placeholder="Enter feedback"
        onChange={(e) => setFeedback(e.target.value)}
        style={{ fontSize: 11 }}
      />
      <Button
        type="primary"
        loading={submitting}
        onClick={handleSubmit}
        style={{
          background: "#426bba",
          borderColor: "#426bba",
          fontWeight: 600,
          fontSize: 11,
        }}
      >
        Submit
      </Button>
    </Space.Compact>
  );
};

// ─── Expanded Row ─────────────────────────────────────────────────────────────

const ExpandedRow = ({ record, adminId, onFeedbackSuccess }) => {
  const metadata = record.metadata || {};

  const metadataEntries = [
    ...Object.entries(metadata)
      .filter(([key]) => METADATA_KEY_ORDER.includes(key))
      .sort(([a], [b]) => METADATA_KEY_ORDER.indexOf(a) - METADATA_KEY_ORDER.indexOf(b)),
    ...Object.entries(metadata).filter(([key]) => !METADATA_KEY_ORDER.includes(key)),
  ];

  const metadataChunks = chunkArray(metadataEntries, 3);

  return (
    <div>
      {/* 1. PV Classification card */}
      <Card bodyStyle={{ padding: "6px 10px" }} style={{ marginBottom: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ fontSize: 11 }}>
            Classification (PV Related or Not):{" "}
            <b>
              {record.is_pv === true
                ? "PV"
                : record.is_pv === false
                  ? "Non-PV"
                  : "—"}
            </b>
          </span>
          <Space size="small">
            {record.feedback === true ? (
              <LikeFilled style={{ color: "#52c41a" }} />
            ) : record.feedback === false ? (
              <DislikeFilled style={{ color: "#ff4d4f" }} />
            ) : null}
            <ConfidenceChip score={record?.pv_confidence} />
          </Space>
        </div>
      </Card>

      {/* 2. Metadata cards — 3 per row */}
      {metadataChunks.map((row, idx) => (
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
                    {value?.is_liked === true ? (
                      <LikeFilled style={{ color: "#52c41a", fontSize: 13 }} />
                    ) : value?.is_liked === false ? (
                      <DislikeFilled style={{ color: "#ff4d4f", fontSize: 13 }} />
                    ) : <span style={{ color: "#bbb", fontSize: 11 }}>—</span>
                    }
                    <ConfidenceChip score={percentage} />
                  </Space>
                </div>
              </Card>
            );
          })}
          {row.length < 3 &&
            Array.from({ length: 3 - row.length }).map((_, i) => (
              <div key={`pad-${i}`} style={{ flex: 1 }} />
            ))}
        </div>
      ))}

      {/* 3. Original Language */}
      <Card bodyStyle={{ padding: "6px 10px" }} style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: "#2c4c91" }}>
          <b>Original Language:</b> {record.orig_language || "—"}
        </div>
      </Card>

      {/* 4. Reason collapse */}
      {record.reason && (
        <Card bodyStyle={{ padding: "8px 12px" }} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 12 }}><b>Reason:</b></div>
          <div style={{ fontSize: 11, marginTop: 4 }}>
            <Collapse>
              <Panel header="Reason" key="1">
                <div style={{ fontSize: 11, whiteSpace: "pre-wrap", lineHeight: 1.5, color: "#2c4c91" }}>
                  {record.reason}
                </div>
              </Panel>
            </Collapse>
          </div>
        </Card>
      )}

      {/* 5. Comments + Admin Feedback */}
      <div style={{ marginTop: 12 }}>
        <div style={{ fontSize: 12, marginBottom: 4, color: "#2c4c91" }}>
          Classification Comment
        </div>
        <Input.TextArea
          rows={2}
          readOnly
          value={record.classification_comment || ""}
          placeholder="No classification comment"
          style={{ marginBottom: 10, fontSize: 11 }}
        />

        <div style={{ fontSize: 12, marginBottom: 4, color: "#2c4c91" }}>
          Extraction Comment
        </div>
        <Input.TextArea
          rows={2}
          readOnly
          value={record.extraction_comment || ""}
          placeholder="No extraction comment"
          style={{ marginBottom: 10, fontSize: 11 }}
        />

        {/* 6. Admin Feedback with history icon */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
          <span style={{ fontSize: 12, color: "#2c4c91" }}>Admin Feedback</span>
          <FeedbackHistoryPopover fileId={record.file_id} />
        </div>
        <FeedbackCell
          record={record}
          adminId={adminId}
          onSuccess={onFeedbackSuccess}
        />
      </div>
    </div>
  );
};

// ─── MonitoringTable ──────────────────────────────────────────────────────────

const MonitoringTable = ({ user, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [tableData, setTableData] = useState([]);
  const [expandedRowKeys, setExpandedRowKeys] = useState([]);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 10,
    total: 0,
  });

  const handleFeedbackSuccess = (fileId, feedback, adminId) => {
    setTableData((prev) =>
      prev.map((row) =>
        row.file_id === fileId
          ? { ...row, admin_feedback: feedback, admin_id: adminId }
          : row
      )
    );
  };

  const loadData = async (page = 1, pageSize = 10) => {
    try {
      setLoading(true);
      const response = await getAllFeedback({ page_number: page });

      const rows = (response?.data || []).map((item) => {
        const metaValues = Object.values(item.metadata || {});

        // Count upvotes: PV feedback + all metadata is_liked === true
        const upvoteCount =
          (item.feedback === true ? 1 : 0) +
          metaValues.filter((v) => v?.is_liked === true).length;

        // Count downvotes: PV feedback + all metadata is_liked === false
        const downvoteCount =
          (item.feedback === false ? 1 : 0) +
          metaValues.filter((v) => v?.is_liked === false).length;

        return {
          ...item,
          upvote_count: upvoteCount,
          downvote_count: downvoteCount,
          // Flatten is_liked per key for ExpandedRow quick access
          ...Object.entries(item.metadata || {}).reduce((acc, [key, value]) => {
            acc[key] = value?.is_liked;
            return acc;
          }, {}),
        };
      });

      setTableData(rows);
      setPagination({
        current: response.page_number ?? page,
        pageSize: response.page_size ?? pageSize,
        total: response.total_count ?? 0,
      });
    } catch (error) {
      console.error(error);
      message.error("Failed to load monitoring data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const columns = [
    {
      title: "User ID",
      dataIndex: "user_id",
      width: 200,
      ellipsis: true,
      render: (text) => <span style={{ fontSize: 11 }}>{text}</span>,
    },
    {
      title: "File Name",
      dataIndex: "file_name",
      ellipsis: true,
      render: (text) => <span style={{ fontSize: 11 }}>{text}</span>,
    },
    {
      title: "PV Status",
      dataIndex: "is_pv",
      width: 100,
      align: "center",
      render: (val) => {
        if (val === true) return <Tag color="red">PV</Tag>;
        if (val === false) return <Tag>Non-PV</Tag>;
        return <Tag color="default">—</Tag>;
      },
    },
    {
      // PV Verdict: whether the user liked or disliked the PV classification
      title: "PV Verdict",
      dataIndex: "feedback",
      width: 110,
      align: "center",
      render: (val) => {
        if (val === true)
          return (
            <Space size={4}>
              <LikeFilled style={{ color: "#52c41a" }} />
              <span style={{ fontSize: 11, color: "#52c41a" }}>Liked</span>
            </Space>
          );
        if (val === false)
          return (
            <Space size={4}>
              <DislikeFilled style={{ color: "#ff4d4f" }} />
              <span style={{ fontSize: 11, color: "#ff4d4f" }}>Disliked</span>
            </Space>
          );
        return <span style={{ color: "#bbb", fontSize: 11 }}>—</span>;
      },
    },
    {
      // Total likes across PV feedback + all metadata fields
      title: "Like Count",
      dataIndex: "upvote_count",
      width: 90,
      align: "center",
      render: (count) => (
        <Space size={4}>
          <LikeFilled style={{ color: "#52c41a", fontSize: 13 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: "#2c4c91" }}>
            {count ?? 0}
          </span>
        </Space>
      ),
    },
    {
      // Total dislikes across PV feedback + all metadata fields
      title: "Dislike Count",
      dataIndex: "downvote_count",
      width: 100,
      align: "center",
      render: (count) => (
        <Space size={4}>
          <DislikeFilled style={{ color: "#ff4d4f", fontSize: 13 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: "#2c4c91" }}>
            {count ?? 0}
          </span>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", marginTop: "1rem", gap: "2rem", padding: "1rem" }}>
        <StyledButton type="primary" onClick={() => onClose(false)}>
          Back
        </StyledButton>
      </div>

      <StyledTableWrapper>
        <Table
          rowKey="file_id"
          loading={loading}
          dataSource={tableData}
          columns={columns}
          scroll={{ y: 500 }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            pageSizeOptions: ["10", "20", "50", "100"],
            showTotal: (total, range) =>
              `${range[0]}–${range[1]} of ${total} records`,
          }}
          onChange={(pager) => loadData(pager.current, pager.pageSize)}
          expandable={{
            expandedRowKeys,
            expandedRowRender: (record) => (
              <ExpandedRow
                record={record}
                adminId={user?.username || user?.email || user?.id || user?.userId || ""}
                onFeedbackSuccess={handleFeedbackSuccess}
              />
            ),
            onExpand: (expanded, record) => {
              setExpandedRowKeys(
                expanded
                  ? [...expandedRowKeys, record.file_id]
                  : expandedRowKeys.filter((k) => k !== record.file_id)
              );
            },
          }}
        />
      </StyledTableWrapper>
    </>
  );
};

export default MonitoringTable;