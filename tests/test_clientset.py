"""Tests for clientset"""

import os
from unittest.mock import patch

import pytest
import yaml

from cloudcoil.client._client_set import (
    ClientSet,
)


@pytest.mark.parametrize(
    "kubeconfig_content,expected",
    [
        # Test case 1: Basic kubeconfig
        (
            {
                "current-context": "test-context",
                "contexts": [
                    {
                        "name": "test-context",
                        "context": {
                            "cluster": "test-cluster",
                            "user": "test-user",
                            "namespace": "test-ns",
                        },
                    }
                ],
                "clusters": [
                    {"name": "test-cluster", "cluster": {"server": "https://test-server"}}
                ],
                "users": [{"name": "test-user", "user": {"token": "test-token"}}],
            },
            {"server": "https://test-server", "namespace": "test-ns", "token": "test-token"},
        ),
        # Test case 2: Kubeconfig with certificate data
        (
            {
                "current-context": "test-context",
                "contexts": [
                    {
                        "name": "test-context",
                        "context": {"cluster": "test-cluster", "user": "test-user"},
                    }
                ],
                "clusters": [
                    {
                        "name": "test-cluster",
                        "cluster": {
                            "server": "https://test-server",
                            "certificate-authority-data": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJkakNDQVIyZ0F3SUJBZ0lCQURBS0JnZ3Foa2pPUFFRREFqQWpNU0V3SHdZRFZRUUREQmhyTTNNdGMyVnkKZG1WeUxXTmhRREUzTXpVME1EY3lOek13SGhjTk1qUXhNakk0TVRjek5ETXpXaGNOTXpReE1qSTJNVGN6TkRNegpXakFqTVNFd0h3WURWUVFEREJock0zTXRjMlZ5ZG1WeUxXTmhRREUzTXpVME1EY3lOek13V1RBVEJnY3Foa2pPClBRSUJCZ2dxaGtqT1BRTUJCd05DQUFTeGVETlErSE9FVHZDUUtSWTVqR2JCblUwcXBBUHM2akNyeFE5QXBpd0YKWXJqMlZSOFBEUnVYWWE1L1o5STRlT0NxSkljZWFjckNVUUNRUUhOZU94Y1hvMEl3UURBT0JnTlZIUThCQWY4RQpCQU1DQXFRd0R3WURWUjBUQVFIL0JBVXdBd0VCL3pBZEJnTlZIUTRFRmdRVUJXWDhYelZQcDF5d3YwZXRXQlpOCnNEbmpTckl3Q2dZSUtvWkl6ajBFQXdJRFJ3QXdSQUlnYWx0RmNxTGlXNTdiemxlYXFVV1pXOXhTTTM2OUFmK2EKamNUakZJZ0ZzZHNDSUNYR3lid2pUUTVMZk1taFRoTytMaGhxT1ZpdDBQV1JMN1dTV255NDlSTGQKLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo=",  # base64 encoded "certdata"
                        },
                    }
                ],
                "users": [
                    {
                        "name": "test-user",
                        "user": {
                            "client-certificate-data": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUJrakNDQVRlZ0F3SUJBZ0lJV2hxakpvUFR6Qkl3Q2dZSUtvWkl6ajBFQXdJd0l6RWhNQjhHQTFVRUF3d1kKYXpOekxXTnNhV1Z1ZEMxallVQXhOek0xTkRBM01qY3pNQjRYRFRJME1USXlPREUzTXpRek0xb1hEVEkxTVRJeQpPREUzTXpRek0xb3dNREVYTUJVR0ExVUVDaE1PYzNsemRHVnRPbTFoYzNSbGNuTXhGVEFUQmdOVkJBTVRESE41CmMzUmxiVHBoWkcxcGJqQlpNQk1HQnlxR1NNNDlBZ0VHQ0NxR1NNNDlBd0VIQTBJQUJBaXVzZ3ExcG9QYkM3S3AKbVU4UmRKZDU1K3BkY1dVZkF1Z3h1S29ucEMxVmpERHRXaEpEWkxycktsQWk4ZkxlMkJRV29aOEVXSDNkTmxtVwpmb093K2RXalNEQkdNQTRHQTFVZER3RUIvd1FFQXdJRm9EQVRCZ05WSFNVRUREQUtCZ2dyQmdFRkJRY0RBakFmCkJnTlZIU01FR0RBV2dCVHZTQlQrVk83b2s5MkJ5T2pkRnRacmo5a21oVEFLQmdncWhrak9QUVFEQWdOSkFEQkcKQWlFQXZVcGdYU3d2akpkaUdaUEJJVHhnTmNZdHA2VDVJbjN2eDUzRmZXeGVlcjRDSVFDWDhveWZwVGl5aTljSQplNGRlUTdSR1ZuaTErNDhabXBOL1M5QXRNd2pIV0E9PQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCi0tLS0tQkVHSU4gQ0VSVElGSUNBVEUtLS0tLQpNSUlCZHpDQ0FSMmdBd0lCQWdJQkFEQUtCZ2dxaGtqT1BRUURBakFqTVNFd0h3WURWUVFEREJock0zTXRZMnhwClpXNTBMV05oUURFM016VTBNRGN5TnpNd0hoY05NalF4TWpJNE1UY3pORE16V2hjTk16UXhNakkyTVRjek5ETXoKV2pBak1TRXdId1lEVlFRRERCaHJNM010WTJ4cFpXNTBMV05oUURFM016VTBNRGN5TnpNd1dUQVRCZ2NxaGtqTwpQUUlCQmdncWhrak9QUU1CQndOQ0FBU2hrNHpxa2dXNU96NnMzNWpoa0JzenBtazRwS0ROa2FKWGpaWTlIakcvCkR3N0VwcXFLT0prTEQvbEZjUk9nY1czdDBZajgxM3pOTmpXcmdUbTN4YjY3bzBJd1FEQU9CZ05WSFE4QkFmOEUKQkFNQ0FxUXdEd1lEVlIwVEFRSC9CQVV3QXdFQi96QWRCZ05WSFE0RUZnUVU3MGdVL2xUdTZKUGRnY2pvM1JiVwphNC9aSm9Vd0NnWUlLb1pJemowRUF3SURTQUF3UlFJZ2VvTWViOFcrRzFpTjZDcW5tQm5QOGg4TDYzNWsrTXhFCnJzNnBYYUN1SEFJQ0lRRERJVWRlR1BjTUQ2eW1JVE1xbnBuUVkxMFp3cGkzQWxZUVFJcDNjb05iM2c9PQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg==",  # base64 encoded "clientcert"
                            "client-key-data": "LS0tLS1CRUdJTiBFQyBQUklWQVRFIEtFWS0tLS0tCk1IY0NBUUVFSU8wN1hGT0lmTVFyS3Z6Skp4OEkrbnpCQXdnZmpuVGdWZ3o4L2JiRi9Sc1hvQW9HQ0NxR1NNNDkKQXdFSG9VUURRZ0FFQ0s2eUNyV21nOXNMc3FtWlR4RjBsM25uNmwxeFpSOEM2REc0cWlla0xWV01NTzFhRWtOawp1dXNxVUNMeDh0N1lGQmFobndSWWZkMDJXWlorZzdENTFRPT0KLS0tLS1FTkQgRUMgUFJJVkFURSBLRVktLS0tLQo=",  # base64 encoded "clientkey"
                        },
                    }
                ],
            },
            {"server": "https://test-server", "namespace": "default"},
        ),
    ],
)
def test_kubeconfig_initialization(kubeconfig_content, expected, tmp_path):
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text(yaml.dump(kubeconfig_content))

    with patch.dict(os.environ, {"KUBECONFIG": str(kubeconfig)}):
        client = ClientSet()
        assert client.server == expected["server"]
        assert client.namespace == expected["namespace"]
        if "token" in expected:
            assert client.token == expected["token"]


@pytest.mark.parametrize(
    "params,expected",
    [
        (
            {"server": "https://custom-server", "namespace": "custom-ns", "token": "custom-token"},
            {"server": "https://custom-server", "namespace": "custom-ns", "token": "custom-token"},
        ),
        (
            {"server": "https://custom-server"},
            {"server": "https://custom-server", "namespace": "default", "token": None},
        ),
    ],
)
def test_direct_parameter_initialization(
    params,
    expected,
):
    client = ClientSet(**params)
    assert client.server == expected["server"]
    assert client.namespace == expected["namespace"]
    assert client.token == expected["token"]


@pytest.mark.parametrize(
    "kubeconfig_content",
    [
        {"current-context": "test-context"},  # Missing required sections
        {
            "current-context": "test-context",
            "contexts": [],
            "clusters": [],
            "users": [],
        },  # Empty required sections
        {"contexts": [], "clusters": [], "users": []},  # Missing current-context
    ],
)
def test_invalid_kubeconfig(kubeconfig_content, tmp_path):
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text(yaml.dump(kubeconfig_content))

    with patch.dict(os.environ, {"KUBECONFIG": str(kubeconfig)}):
        with pytest.raises(ValueError):
            ClientSet()


def test_incluster_initialization(tmp_path):
    token_path = tmp_path / "token"
    ca_path = tmp_path / "ca.crt"
    namespace_path = tmp_path / "namespace"

    # Create mock in-cluster files
    token_path.write_text("test-token")
    namespace_path.write_text("test-namespace")

    with patch("cloudcoil.client._client_set.INCLUSTER_TOKEN_PATH", token_path), patch(
        "cloudcoil.client._client_set.INCLUSTER_CERT_PATH", ca_path
    ), patch("cloudcoil.client._client_set.DEFAULT_KUBECONFIG", tmp_path / "dne"), patch(
        "cloudcoil.client._client_set.INCLUSTER_NAMESPACE_PATH", namespace_path
    ):
        client = ClientSet()
        assert client.server == "https://kubernetes.default.svc"
        assert client.namespace == "test-namespace"
        assert client.token == "test-token"
