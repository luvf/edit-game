import numpy as np
import torch
from torch import nn
from tqdm import tqdm

device = torch.cpu


def train_and_val(model, data, num_epochs, lr, wd, verbose=True):
    """Model training

    Args:
        model (pyg): model trained, previously defined
        data (torch_geometric.Data): dataset the model is trained on
        num_epochs (int): number of epochs
        lr (float): learning rate
        wd (float): weight decay
        verbose (bool, optional): print information. Defaults to True.

    """
    # Define the optimizer for the learning process
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
    loss_fn = nn.CrossEntropyLoss()
    # Training and eval modes
    train_loss_values, train_acc_values = [], []
    val_loss_values, val_acc_values = [], []

    best = np.inf
    bad_counter = 0

    for epoch in tqdm(range(num_epochs), desc="Training", leave=False):
        train(train_dataloader, model, loss_fn, optimizer)
        test(test_dataloader, model, loss_fn)


def train(dataloader, model, loss_fn, optimizer):
    size = len(dataloader.dataset)
    model.train()
    for batch, (X, y) in enumerate(dataloader):
        X, y = X.to(device), y.to(device)

        # Compute prediction error
        pred = model(X)
        loss = loss_fn(pred, y)

        # Backpropagation
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()

        if batch % 100 == 0:
            loss, current = loss.item(), (batch + 1) * len(X)
            print(f"loss: {loss:>7f}  [{current:>5d}/{size:>5d}]")


def test_loop(dataloader, model, loss_fn):
    size = len(dataloader.dataset)
    num_batches = len(dataloader)
    test_loss, correct = 0, 0

    with torch.no_grad():
        for X, y in dataloader:
            pred = model(X)
            test_loss += loss_fn(pred, y).item()
            correct += (pred.argmax(1) == y).type(torch.float).sum().item()

    test_loss /= num_batches
    correct /= size
    print(
        f"Test Error: \n Accuracy: {(100*correct):>0.1f}%, Avg loss: {test_loss:>8f} \n"
    )
