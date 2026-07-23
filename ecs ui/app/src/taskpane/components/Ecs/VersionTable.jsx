import React from "react";
import { Spin, Table, Tooltip } from "antd";
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
  /* ===== CLICKABLE CURSOR ===== */
  .ant-table-tbody > tr {
    cursor: pointer;
  }
`;

const VersionTable = ({ versions, loading, onSelectVersion }) => {

    const tableData = versions.map((item) => ({
        key: item.crf_file_id,
        crf_file_id: item.crf_file_id,
        date: new Date(item.created_at).toLocaleString(),
        fileName: item.crf_file_path.split("/").pop(),
    }));

    const columns = [
        {
            title: "Date",
            dataIndex: "date",
            key: "date",
        },
        {
            title: "File Name",
            dataIndex: "fileName",
            key: "fileName",
        },
    ];


    return (

        <StyledTableWrapper>
            <div style={{ padding: "14px 10px" }}>
                <Spin spinning={loading}>
                    <Table
                        dataSource={tableData}
                        columns={columns}
                        size="small"
                        pagination={{
                            pageSize: 5,
                            size: "small",
                        }}
                        onRow={(record) => ({
                            onClick: () => {
                                onSelectVersion?.(record);
                            },
                        })}
                    />
                </Spin>
            </div>
        </StyledTableWrapper>

    );
};

export default VersionTable;
