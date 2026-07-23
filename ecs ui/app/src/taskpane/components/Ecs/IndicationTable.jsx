import React, { useEffect, useState } from "react";
import { Table, Select, Spin } from "antd";
import { getIndication } from "../../../services";
import styled from "styled-components";
import "./indication.css"

export const StyledTableWrapper = styled.div`
  .ant-table-thead > tr > th {
    background: #426bba !important;
    border: 1px solid #426bba;
    color: #fefeff !important;
    font-weight: 600;
    font-size: 12px;
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
  }
`;

const toCamelTitle = (str) => {
    return str
        .replace(/_/g, " ")                // replace underscore with space
        .replace(/\w\S*/g, (txt) =>
            txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
        );
};

const API_MAP = {
    "Indication": "indication",
    "Molecule": "molecule",
    "Therapeutic Area": "ta",
};

const cleanOptions = (arr) =>
    (arr || []).filter(
        (item) => item !== null && item !== undefined && item !== "" && !Number.isNaN(item)
    );


const IndicationTable = ({ onValuesChange }) => {
    const [tableData, setTableData] = useState([]);
    const [loading, setLoading] = useState(true);

    // Simulated API call
    const fetchData = async () => {
        try {
            const response = await getIndication()
            const apiResponse = response?.response
            // Convert API object → table rows
            const formatted = Object.keys(apiResponse).map((key, index) => ({
                key: index,
                attribute: toCamelTitle(key),
                rawKey: key,
                options: cleanOptions(apiResponse[key]),
                value: ''
            }));

            setTableData(formatted);

        } catch (error) {
            console.log(error)
        } finally {
            setLoading(false)
        }

    };

    useEffect(() => {
        fetchData();
    }, []);

    // Handle dropdown change
    const updateValue = (key, selectedValue) => {
        const updated = tableData.map(row =>
            row.key === key ? { ...row, value: selectedValue } : row
        );

        setTableData(updated);
        // Pass selected values to parent
        if (onValuesChange) {
            const output = updated.reduce((acc, row) => {
                const keyName = API_MAP[row.attribute] || row.attribute;
                acc[keyName] = row.value;
                return acc;
            }, {});
            onValuesChange(output);
        }
    };

    const columns = [
        {
            title: "Attribute",
            dataIndex: "attribute",
            key: "attribute",
            width: "35%",
        },
        {
            title: "Value",
            dataIndex: "value",
            key: "value",
            width: "65%",
            render: (value, record) => (
                <Select
                    style={{
                        width: "100%",
                        fontSize: 12,         // selected text size
                    }}
                    dropdownStyle={{
                        fontSize: 12,         // dropdown text size
                        whiteSpace: "normal", // allow wrapping in options
                        maxWidth: 300,
                    }}
                    listHeight={300}
                    optionRender={(option) => (
                        <div style={{
                            fontSize: 12,
                            whiteSpace: "normal",
                            lineHeight: "16px"
                        }}>
                            {option.label}
                        </div>
                    )}
                    // Allow wrapping in the selected (display) area
                    dropdownMatchSelectWidth={false}
                    showArrow
                    value={value}
                    placeholder="Select value"
                    options={record.options.map((i) => ({ label: i, value: i }))}
                    onChange={(val) => updateValue(record.key, val)}
                />


            )
        }
    ];

    return (
        <StyledTableWrapper>
            <Spin spinning={loading}>
                <Table
                    dataSource={tableData}
                    columns={columns}
                    pagination={false}
                />
            </Spin>
        </StyledTableWrapper>
    );
};

export default IndicationTable;
