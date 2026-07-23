import React from "react";
import { Table, Tooltip } from "antd";
import { DeleteOutlined } from "@ant-design/icons";
import styled from "styled-components";

export const StyledTableWrapper = styled.div`
  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
    line-height: 1.2;
  }

  .ant-table-tbody > tr > td {
    background: linear-gradient(
      150deg,
      rgba(235, 240, 255, 1) 25%,
      rgba(225, 235, 255, 1) 50%,
      rgba(215, 230, 255, 1) 100%
    );
    border: 1px solid #bfd3f2;
    color: #2c4c91;
    font-size: 11px;
    padding: 6px 12px;
    line-height: 1;
  }
`;

const formatSize = (bytes) =>
  bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(2)} MB`
    : `${(bytes / 1024).toFixed(2)} KB`;

const FileTable = ({ fileList, onRemove, jobId }) => {

  const fileTableData = fileList.map((file) => ({
    key: file.uid,
    name: file.name || file.file_name,
    size: file.size ? formatSize(file.size) : formatSize(file.file_size_bytes),
    file
  }));

  const columns = [
    {
      title: "Contract",
      dataIndex: "name",
      key: "name",
      ellipsis: true,
      render: (text) => (
        <Tooltip title={text}>
          <span
            style={{
              fontSize: 10,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "block",
              maxWidth: "100%"
            }}
          >
            {text}
          </span>
        </Tooltip>
      )
    },
    {
      title: "Size",
      dataIndex: "size",
      key: "size",
      width: 80,
      align: "center",
      render: (size) => (
        <span style={{ fontSize: 10 }}>
          {size}
        </span>
      )
    },
    ...(jobId ? [] : [{
      title: "Remove",
      key: "remove",
      width: 60,
      align: "center",
      render: (_, record) => (
        <Tooltip title="Remove">
          <DeleteOutlined
            style={{
              color: "#ff4d4f",
              fontSize: 10,
              cursor: "pointer"
            }}
            onClick={() => onRemove(record.file)}
          />
        </Tooltip>
      )
    }])

  ];

  return (
    <StyledTableWrapper>
      <Table
        dataSource={fileTableData}
        columns={columns}
        pagination={false}
        tableLayout="fixed"
        scroll={{ x: "100%" }}
      />
    </StyledTableWrapper>
  );
};

export default FileTable;
