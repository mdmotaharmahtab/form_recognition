import React from "react";
import { Table, Tooltip } from "antd";
import styled, { createGlobalStyle } from "styled-components";

export const StyledTableWrapper = styled.div`
  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid #426bba;
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

const TemplateTable = ({ columns, dataSource }) => {
  return (
    <>
      <StyledTableWrapper>
        <Table dataSource={dataSource} columns={columns} pagination={false} />
      </StyledTableWrapper>
    </>
  );
};

export default TemplateTable;
