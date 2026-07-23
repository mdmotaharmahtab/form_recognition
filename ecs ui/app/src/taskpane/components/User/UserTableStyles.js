// UserTableStyles.js

import styled from "styled-components";

export const StyledTableWrapper = styled.div`
  width: 100%;
  overflow: auto;

  .ant-table {
    border-radius: 8px;
    overflow: hidden;
  }

  .ant-table-container {
    overflow: auto;
  }

  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 12px;
    white-space: nowrap;
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

    word-break: break-word;
  }

  .edit-icon {
    cursor: pointer;
    color: #426bba;
    font-size: 14px;
    transition: 0.2s;
  }

  .edit-icon:hover {
    transform: scale(1.1);
  }
`;