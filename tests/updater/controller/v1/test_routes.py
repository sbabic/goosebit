import pytest

from goosebit.models import Firmware, Hardware
from goosebit.updater.manager import get_update_manager

UUID = "221326d9-7873-418e-960c-c074026a3b7c"


async def _api_login(async_client):
    login_data = {"username": "admin@goosebit.local", "password": "admin"}
    response = await async_client.post("/login", data=login_data, follow_redirects=True)
    assert response.status_code == 200


async def _api_device_update(async_client, device, update_attribute, update_value):
    response = await async_client.post(
        f"/api/devices/update",
        json={"devices": [f"{device.uuid}"], update_attribute: update_value},
    )
    assert response.status_code == 200


async def _api_devices_get(async_client):
    response = await async_client.get("/api/devices/all")
    assert response.status_code == 200
    return response.json()


async def _api_rollouts_get(async_client):
    response = await async_client.get("/api/rollouts/all")
    assert response.status_code == 200
    return response.json()


async def _poll_first_time(async_client):
    response = await async_client.get(f"/DEFAULT/controller/v1/{UUID}")
    assert response.status_code == 200
    data = response.json()
    assert "config" in data
    assert "_links" in data
    config_url = data["_links"]["configData"]["href"]
    assert config_url == f"http://test/DEFAULT/controller/v1/{UUID}/configData"
    return config_url


async def _register(async_client, config_url):
    # register device
    response = await async_client.put(
        config_url,
        json={
            "id": "",
            "status": {
                "result": {"finished": "success"},
                "execution": "closed",
                "details": [""],
            },
            "data": {
                "hw_model": "smart-gateway-mt7688",
                "installed_version": "8.8.1-12-g302f635+189128",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert data["message"] == "Updated swupdate data."


async def _poll(
    async_client, device_uuid, firmware: Firmware | None, expect_update=True
):
    response = await async_client.get(f"/DEFAULT/controller/v1/{device_uuid}")

    assert response.status_code == 200
    data = response.json()
    if expect_update:
        deployment_base = data["_links"]["deploymentBase"]["href"]
        assert (
            deployment_base
            == f"http://test/DEFAULT/controller/v1/{device_uuid}/deploymentBase/{firmware.id}"
        )
        return deployment_base
    else:
        assert data["_links"] == {}
        return None


async def _retrieve_firmware_url(async_client, deployment_base, firmware):
    response = await async_client.get(deployment_base)
    assert response.status_code == 200
    data = response.json()
    assert data["deployment"]["download"] == "forced"
    assert data["deployment"]["update"] == "forced"
    assert data["id"] == str(firmware.id)
    assert (
        data["deployment"]["chunks"][0]["artifacts"][0]["_links"]["download"]["href"]
        == f"http://test/api/download/{firmware.id}"
    )
    assert (
        data["deployment"]["chunks"][0]["artifacts"][0]["hashes"]["sha1"]
        == firmware.hash
    )
    assert data["deployment"]["chunks"][0]["artifacts"][0]["size"] == firmware.size

    return data["deployment"]["chunks"][0]["artifacts"][0]["_links"]["download"]["href"]


async def _feedback(async_client, device_uuid, firmware, finished, execution):
    response = await async_client.post(
        f"/DEFAULT/controller/v1/{device_uuid}/deploymentBase/{firmware.id}/feedback",
        json={
            "id": firmware.id,
            "status": {
                "result": {"finished": finished},
                "execution": execution,
                "details": [""],
            },
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_register_device(async_client, test_data):
    config_url = await _poll_first_time(async_client)

    await _register(async_client, config_url)

    await _poll(async_client, UUID, None, False)

    await _api_login(async_client)
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Registered"


@pytest.mark.asyncio
async def test_rollout_full(async_client, test_data):
    device = test_data["device_rollout"]
    firmware = test_data["firmware_latest"]
    rollout = test_data["rollout_default"]

    deployment_base = await _poll(async_client, device.uuid, firmware)

    await _retrieve_firmware_url(async_client, deployment_base, firmware)

    # confirm installation start (in reality: several of similar posts)
    await _feedback(async_client, device.uuid, firmware, "none", "proceeding")
    await _api_login(async_client)
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Running"

    # report finished installation
    await _feedback(async_client, device.uuid, firmware, "success", "closed")
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Finished"
    assert devices[0]["fw"] == firmware.version

    await rollout.refresh_from_db()
    rollouts = await _api_rollouts_get(async_client)
    assert rollouts[0]["success_count"] == 1
    assert rollouts[0]["failure_count"] == 0


@pytest.mark.asyncio
async def test_rollout_signalling_download_failure(async_client, test_data):
    device = test_data["device_rollout"]
    firmware = test_data["firmware_latest"]

    deployment_base = await _poll(async_client, device.uuid, firmware)

    firmware_url = await _retrieve_firmware_url(async_client, deployment_base, firmware)

    # confirm installation start (in reality: several of similar posts)
    await _feedback(async_client, device.uuid, firmware, "none", "proceeding")
    await _api_login(async_client)
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Running"

    # HEAD /api/download/1 HTTP/1.1 (reason not clear)
    response = await async_client.head(firmware_url)
    assert response.status_code == 200
    assert response.headers["Content-Length"] == "1200"

    # GET /api/download/1 HTTP/1.1
    response = await async_client.get(firmware_url)
    assert response.status_code == 200

    # report failure
    await _feedback(async_client, device.uuid, firmware, "failure", "closed")
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Error"


@pytest.mark.asyncio
async def test_latest(async_client, test_data):
    device = test_data["device_rollout"]
    firmware = test_data["firmware_latest"]

    await _api_login(async_client)
    await _api_device_update(async_client, device, "firmware", "latest")

    deployment_base = await _poll(async_client, device.uuid, firmware)

    await _retrieve_firmware_url(async_client, deployment_base, firmware)

    # confirm installation start (in reality: several of similar posts)
    await _feedback(async_client, device.uuid, firmware, "none", "proceeding")
    await _api_login(async_client)
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Running"

    # report finished installation
    await _feedback(async_client, device.uuid, firmware, "success", "closed")
    devices = await _api_devices_get(async_client)
    assert devices[0]["state"] == "Finished"
    assert devices[0]["fw"] == firmware.version


@pytest.mark.asyncio
async def test_latest_with_no_firmware_available(async_client, test_data):
    device = test_data["device_rollout"]

    await _api_login(async_client)
    await _api_device_update(async_client, device, "firmware", "latest")

    fake_hardware = await Hardware.create(model="does-not-exist", revision="default")
    device.hardware_id = fake_hardware.id
    await device.save()

    await _poll(async_client, device.uuid, None, False)


@pytest.mark.asyncio
async def test_pinned(async_client, test_data):
    device = test_data["device_rollout"]

    await _api_login(async_client)
    await _api_device_update(async_client, device, "pinned", True)

    await _poll(async_client, device.uuid, None, False)


@pytest.mark.asyncio
async def test_up_to_date(async_client, test_data):
    device = test_data["device_rollout"]
    firmware = test_data["firmware_latest"]

    await _api_login(async_client)
    await _api_device_update(async_client, device, "firmware", "latest")

    manager = await get_update_manager(dev_id=device.uuid)
    await manager.update_fw_version(firmware.version)

    await _poll(async_client, device.uuid, None, False)