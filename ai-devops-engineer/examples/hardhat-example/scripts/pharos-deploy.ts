import hre from "hardhat";

const { viem } = await hre.network.connect();
const contractName = process.env.PHAROS_CONTRACT_NAME;
const constructorArgs = JSON.parse(process.env.PHAROS_CONSTRUCTOR_ARGS || "[]");

if (!contractName) {
  throw new Error("Missing PHAROS_CONTRACT_NAME");
}

const contract = await viem.deployContract(contractName, constructorArgs);
console.log("Contract address:", contract.address);
